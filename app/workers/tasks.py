from pathlib import Path
from datetime import datetime
from typing import Optional
from contextlib import nullcontext
from sqlalchemy.orm import attributes as _sa_attrs

from app.workers.celery_app import celery_app
from app.infrastructure.db.connection import db
from app.infrastructure.db.repository import SyncUploadSessionRepository, SyncLayerRepository
from app.infrastructure.services.tiling_service import TilingService
from app.infrastructure.services.csw_sync import sync_layer
from app.domain.models import ImportStatus, JobStatus, Layer, LayerType
from app.core.utils import slugify, generate_unique_code_sync
from app.infrastructure.services.file_service import FileService
from app.infrastructure.services.upload_artifact_client import UploadArtifactClient


def _make_progress_callback(layer_id: str, upload_id: str):
    from app.core.exceptions import TilingCancelled
    state = {"last": None}

    def callback(progress: dict) -> None:
        payload = {**progress, "status": "processing"}
        state["last"] = payload
        try:
            with db.get_session() as session:
                current = SyncUploadSessionRepository(session).get_by_id(upload_id)
                if current and current.status == JobStatus.cancelled:
                    raise TilingCancelled(f"Tiling for {upload_id} was cancelled")
                SyncLayerRepository(session).update_progress(layer_id, payload)
                print(f"[progress] Updated {layer_id}: {payload.get('percent', 0)}%")
        except TilingCancelled:
            raise
        except Exception as exc:
            print(f"[progress] Failed to write progress for {layer_id}: {exc}")

    def finalize() -> None:
        last = state["last"]
        if last:
            try:
                with db.get_session() as session:
                    SyncLayerRepository(session).update_progress(
                        layer_id, {**last, "percent": 100, "status": "done"}
                    )
            except Exception as exc:
                print(f"[progress] Failed to finalize progress for {layer_id}: {exc}")

    return callback, finalize


def _release_artifact_lease(artifact_id: Optional[str], lease_id: Optional[str]) -> None:
    """Best-effort lease release so upload_api lifecycle cleanup can reclaim the source."""
    if not artifact_id or not lease_id:
        return
    try:
        UploadArtifactClient().release_lease(artifact_id, lease_id)
        print(f"[tiling] Released artifact lease {lease_id} for {artifact_id}")
    except Exception as exc:
        print(f"[tiling] Failed to release artifact lease {lease_id} for {artifact_id}: {exc}")


@celery_app.task(bind=True, max_retries=3)
def import_shapefile_task(self, upload_id: str):
    """Validate and atomically import every shapefile dataset in one ZIP."""
    from app.core.config import settings
    from app.infrastructure.services.shapefile_import_service import (
        ShapefileConfigurationError,
        ShapefileImportCancelled,
        ShapefileValidationError,
        import_shapefile_to_postgis,
    )

    with db.get_session() as session:
        repo = SyncUploadSessionRepository(session)
        current = repo.get_by_id(upload_id)
        if not current:
            print(f"[shp-import] Upload {upload_id} not found, aborting.")
            return
        if current.import_status == ImportStatus.cancelled:
            print(f"[shp-import] Upload {upload_id} was cancelled before start.")
            return
        filename = current.filename
        artifact_id = current.artifact_id
        local_path = (
            current.final_path
            if current.final_path and not current.final_path.startswith("artifact://")
            else None
        )
        layer_id = current.layer_id
        table_name = current.import_table_name
        repo.set_import_status(upload_id, ImportStatus.processing)

    def progress(processed: int, total: int) -> None:
        with db.get_session() as progress_session:
            progress_repo = SyncUploadSessionRepository(progress_session)
            latest = progress_repo.get_by_id(upload_id)
            if latest and latest.import_status == ImportStatus.cancelled:
                raise ShapefileImportCancelled(f"Import {upload_id} was cancelled")
            progress_repo.update_import_progress(upload_id, processed, total)

    source_context = (
        UploadArtifactClient().materialize(artifact_id, filename)
        if artifact_id
        else nullcontext(Path(local_path) if local_path else None)
    )

    try:
        if not table_name:
            raise ShapefileValidationError("Import table name is missing")
        with source_context as source_path:
            if source_path is None:
                raise ShapefileValidationError("Uploaded ZIP is no longer available")
            result = import_shapefile_to_postgis(
                zip_path=Path(source_path),
                engine=db.get_engine(),
                upload_id=upload_id,
                table_name=table_name,
                layer_id=layer_id,
                max_uncompressed_bytes=settings.SHP_IMPORT_MAX_UNCOMPRESSED_BYTES,
                max_features=settings.SHP_IMPORT_MAX_FEATURES,
                max_compression_ratio=settings.SHP_IMPORT_MAX_COMPRESSION_RATIO,
                batch_size=settings.SHP_IMPORT_BATCH_SIZE,
                progress_callback=progress,
            )

        with db.get_session() as session:
            upload_repo = SyncUploadSessionRepository(session)
            layer_repo = SyncLayerRepository(session)
            layer = layer_repo.get_by_id(layer_id)
            metadata = result.metadata()
            if layer:
                existing_metadata = dict(layer.file_metadata or {})
                existing_metadata["postgis"] = metadata
                layer.file_metadata = existing_metadata
                if not layer.tile_url_template:
                    layer.layer_type = LayerType.postgis
                layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north = result.bbox
                _sa_attrs.flag_modified(layer, "file_metadata")
                session.add(layer)
                session.commit()
            else:
                filename_without_ext = Path(filename).stem
                base_code = slugify(filename_without_ext)
                unique_code = generate_unique_code_sync(base_code, layer_repo.code_exists)
                layer = Layer(
                    id=layer_id,
                    upload_session_id=upload_id,
                    code=unique_code,
                    layer_type=LayerType.postgis,
                    filename=filename,
                    file_type="vector",
                    tile_url_template="",
                    is_active=False,
                    is_visible=False,
                    file_metadata={"postgis": metadata},
                    bbox_west=result.bbox[0],
                    bbox_south=result.bbox[1],
                    bbox_east=result.bbox[2],
                    bbox_north=result.bbox[3],
                )
                layer_repo.create(layer)
            upload_repo.complete_import(upload_id, result.row_count, result.primary_table)
        print(
            f"[shp-import] Imported {result.row_count} rows into "
            f"{len(result.datasets)} geodata tables"
        )
        return metadata
    except ShapefileImportCancelled:
        with db.get_session() as session:
            SyncUploadSessionRepository(session).set_import_status(
                upload_id, ImportStatus.cancelled
            )
        print(f"[shp-import] Import {upload_id} cancelled.")
        return
    except Exception as exc:
        with db.get_session() as session:
            repo = SyncUploadSessionRepository(session)
            current = repo.get_by_id(upload_id)
            if current and current.import_status != ImportStatus.cancelled:
                repo.set_import_status(upload_id, ImportStatus.failed, str(exc))
        if isinstance(exc, (ShapefileValidationError, ShapefileConfigurationError)):
            raise
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=5)
        raise

@celery_app.task(bind=True, max_retries=3)
def publish_geoserver_task(self, upload_id: str, layer_id: str, code: str):
    """Publish an uploaded .shp/.zip to GeoServer in the background.

    Large files previously blocked the HTTP request until the proxy timed
    out (502). Mirrors the old synchronous endpoint body, but runs in a
    worker; the caller polls /uploads/{id}/status.
    """
    from app.infrastructure.services.geoserver_service import GeoServerService
    from app.infrastructure.services.bbox_extractor import extract_bbox_from_file, get_crs_from_file
    from app.core.config import settings

    artifact_id = None
    artifact_lease_id = None
    filename = None
    local_path = None
    try:
        with db.get_session() as session:
            repo = SyncUploadSessionRepository(session)
            current = repo.get_by_id(upload_id)
            if not current:
                print(f"[geoserver] Upload {upload_id} not found, aborting.")
                return
            artifact_id = current.artifact_id
            artifact_lease_id = current.artifact_lease_id
            filename = current.filename
            if current.final_path and not current.final_path.startswith("artifact://"):
                local_path = current.final_path
            repo.set_status(upload_id, JobStatus.processing)

        svc = GeoServerService(
            url=settings.GEOSERVER_URL,
            username=settings.GEOSERVER_USER,
            password=settings.GEOSERVER_PASSWORD,
            workspace=settings.GEOSERVER_WORKSPACE,
        )
        source_ctx = (
            UploadArtifactClient().materialize(artifact_id, filename or "artifact.bin")
            if artifact_id is not None
            else nullcontext(local_path)
        )
        with source_ctx as materialized:
            result = svc.publish_shp(materialized, code)
            bbox = extract_bbox_from_file(materialized) or result.get("bbox")
            crs_str = get_crs_from_file(materialized) if bbox else None

        geoserver_meta = {**result}
        if crs_str:
            geoserver_meta["crs"] = crs_str

        with db.get_session() as session:
            layer_repo = SyncLayerRepository(session)
            existing = layer_repo.get_by_id(layer_id)
            if existing:
                existing.layer_type = LayerType.wms
                existing.tile_url_template = result["wms_url"]
                existing_metadata = dict(existing.file_metadata or {})
                existing_metadata.update({
                    "geoserver": geoserver_meta,
                    "layers": geoserver_meta.get("layer_name"),
                })
                existing.file_metadata = existing_metadata
                existing.bbox_west = bbox[0] if bbox else None
                existing.bbox_south = bbox[1] if bbox else None
                existing.bbox_east = bbox[2] if bbox else None
                existing.bbox_north = bbox[3] if bbox else None
                _sa_attrs.flag_modified(existing, "file_metadata")
                session.add(existing)
                session.commit()
            else:
                upload_session = SyncUploadSessionRepository(session).get_by_id(upload_id)
                layer = Layer(
                    id=layer_id,
                    upload_session_id=upload_id,
                    code=code,
                    layer_type=LayerType.wms,
                    filename=upload_session.filename,
                    file_type="external",
                    tile_url_template=result["wms_url"],
                    file_metadata={"geoserver": geoserver_meta, "layers": geoserver_meta.get("layer_name")},
                    bbox_west=bbox[0] if bbox else None,
                    bbox_south=bbox[1] if bbox else None,
                    bbox_east=bbox[2] if bbox else None,
                    bbox_north=bbox[3] if bbox else None,
                )
                layer_repo.create(layer)
            SyncUploadSessionRepository(session).set_status(upload_id, JobStatus.done)
        _release_artifact_lease(artifact_id, artifact_lease_id)
        print(f"[geoserver] Published {code} for upload {upload_id}")
    except Exception as exc:
        with db.get_session() as session:
            repo = SyncUploadSessionRepository(session)
            current = repo.get_by_id(upload_id)
            if current and current.status != JobStatus.cancelled:
                repo.set_status(upload_id, JobStatus.failed, str(exc))
        will_retry = not isinstance(exc, SystemExit) and self.request.retries < self.max_retries
        if not will_retry:
            _release_artifact_lease(artifact_id, artifact_lease_id)
        if not isinstance(exc, SystemExit):
            raise self.retry(exc=exc, countdown=5)

@celery_app.task(bind=True, max_retries=3)
def process_tiling_task(self, upload_id: str, layer_id: str, file_type: str, source_path: str, output_format: str = "raster", max_zoom: int = None):
    artifact_filename = None
    artifact_id = None
    artifact_lease_id = None
    with db.get_session() as session:
        repo = SyncUploadSessionRepository(session)
        current = repo.get_by_id(upload_id)
        if current and current.status == JobStatus.cancelled:
            print(f"[tiling] Task {upload_id} cancelled before start, aborting.")
            _release_artifact_lease(current.artifact_id, current.artifact_lease_id)
            return
        if current:
            artifact_filename = current.filename
            artifact_id = current.artifact_id
            artifact_lease_id = current.artifact_lease_id
        repo.set_status(upload_id, JobStatus.processing)

        # Create placeholder Layer at start so progress callbacks can update it
        layer_repo = SyncLayerRepository(session)
        try:
            if not layer_repo.get_by_id(layer_id):
                upload_session = repo.get_by_id(upload_id)
                if upload_session:
                    filename_without_ext = Path(upload_session.filename).stem
                    base_code = slugify(filename_without_ext)
                    unique_code = generate_unique_code_sync(base_code, layer_repo.code_exists)
                    placeholder = Layer(
                        id=layer_id,
                        upload_session_id=upload_id,
                        code=unique_code,
                        filename=upload_session.filename,
                        file_type=file_type,
                        layer_type="tile",
                        tile_url_template="",
                        file_metadata={
                            "tile_process": {"percent": 0, "status": "processing"},
                            "source_file": {
                                "filename": upload_session.filename,
                                "upload_id": upload_id,
                                "file_type": file_type,
                                "uploaded_at": datetime.now().isoformat(),
                            }
                        },
                    )
                    layer_repo.create(placeholder)
                    print(f"[tiling] Created placeholder layer {layer_id}")
        except Exception as exc:
            print(f"[tiling] Failed to create placeholder layer {layer_id}: {exc}")

    try:
        style = None
        with db.get_session() as session:
            layer_repo = SyncLayerRepository(session)
            existing = layer_repo.get_by_id(layer_id)
            if existing and existing.file_metadata:
                style = existing.file_metadata.get("style")

        progress_cb, finalize_progress = _make_progress_callback(layer_id, upload_id)
        artifact_id = source_path.removeprefix("artifact://") if source_path.startswith("artifact://") else None
        source_context = (
            UploadArtifactClient().materialize(artifact_id, artifact_filename or "artifact.bin")
            if artifact_id
            else nullcontext(Path(source_path))
        )
        with source_context as materialized_path:
            prepared_path = materialized_path
            if artifact_id:
                prepared_path, _ = FileService.prepare_source_path(Path(materialized_path))
            bounds = TilingService.process_tiling(
                file_type,
                Path(prepared_path),
                layer_id,
                output_format=output_format,
                style=style,
                progress_callback=progress_cb,
                max_zoom=max_zoom,
            )
        finalize_progress()
        _release_artifact_lease(artifact_id, artifact_lease_id)
        with db.get_session() as session:
            upload_repo = SyncUploadSessionRepository(session)
            upload_repo.set_status(upload_id, JobStatus.done)

            upload_session = upload_repo.get_by_id(upload_id)
            if upload_session:
                if output_format == "mvt":
                    layer_type = "mvt"
                    tile_url = f"/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.pbf"
                else:
                    layer_type = "tile"
                    tile_url = f"/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png"

                layer_repo = SyncLayerRepository(session)
                existing_layer = layer_repo.get_by_id(layer_id)
                if existing_layer:
                    # Update placeholder with final tile results (preserve file_metadata)
                    existing_layer.layer_type = layer_type
                    existing_layer.tile_url_template = tile_url
                    existing_layer.bbox_west = bounds[0] if bounds else None
                    existing_layer.bbox_south = bounds[1] if bounds else None
                    existing_layer.bbox_east = bounds[2] if bounds else None
                    existing_layer.bbox_north = bounds[3] if bounds else None
                    # Ensure file_metadata is not lost
                    if not existing_layer.file_metadata:
                        existing_layer.file_metadata = {}
                    _sa_attrs.flag_modified(existing_layer, "file_metadata")
                    session.add(existing_layer)
                    session.commit()
                    try:
                        sync_layer(existing_layer)
                    except Exception:
                        pass
                else:
                    filename_without_ext = Path(upload_session.filename).stem
                    base_code = slugify(filename_without_ext)
                    unique_code = generate_unique_code_sync(base_code, layer_repo.code_exists)
                    layer = Layer(
                        id=layer_id,
                        upload_session_id=upload_id,
                        code=unique_code,
                        filename=upload_session.filename,
                        file_type=file_type,
                        layer_type=layer_type,
                        tile_url_template=tile_url,
                        bbox_west=bounds[0] if bounds else None,
                        bbox_south=bounds[1] if bounds else None,
                        bbox_east=bounds[2] if bounds else None,
                        bbox_north=bounds[3] if bounds else None,
                    )
                    layer_repo.create(layer)
                    try:
                        sync_layer(layer)
                    except Exception:
                        pass
    except Exception as exc:
        from app.core.exceptions import TilingCancelled
        if isinstance(exc, TilingCancelled):
            _release_artifact_lease(artifact_id, artifact_lease_id)
            with db.get_session() as session:
                repo = SyncUploadSessionRepository(session)
                repo.set_status(upload_id, JobStatus.cancelled)
            print(f"[tiling] Task {upload_id} cancelled.")
            return

        # Write failed status to tile_process
        try:
            with db.get_session() as session:
                SyncLayerRepository(session).update_progress(
                    layer_id, {"percent": 0, "status": "failed"}
                )
        except Exception:
            pass

        with db.get_session() as session:
            repo = SyncUploadSessionRepository(session)
            current = repo.get_by_id(upload_id)
            if current and current.status != JobStatus.cancelled:
                repo.set_status(upload_id, JobStatus.failed, error_message=str(exc))
        will_retry = not isinstance(exc, SystemExit) and self.request.retries < self.max_retries
        # Keep the lease across retries (materialize needs it); release once retries are exhausted.
        if not will_retry:
            _release_artifact_lease(artifact_id, artifact_lease_id)
        if not isinstance(exc, SystemExit):
            raise self.retry(exc=exc, countdown=5)


def _make_download_progress_callback(layer_id: str):
    from app.infrastructure.services.esri_downloader import DownloadCancelled

    def callback(progress: dict) -> None:
        with db.get_session() as session:
            repo = SyncLayerRepository(session)
            current = repo.get_download_progress(layer_id) or {}
            if current.get("status") == "cancelled":
                raise DownloadCancelled(f"Download for layer {layer_id} cancelled")

            sub_total = progress.get("sublayers_total") or 1
            sub_done = progress.get("sublayers_done") or 0
            feat_total = progress.get("features_total") or 0
            feat_done = progress.get("features_done") or 0
            sub_fraction = (feat_done / feat_total) if feat_total else 0
            percent = int(((sub_done + min(sub_fraction, 1)) / sub_total) * 100) if sub_total else 0
            payload = {
                **progress,
                "task_id": current.get("task_id"),
                "started_at": current.get("started_at"),
                "percent": min(percent, 99),
                "status": "processing",
            }
            repo.update_download_progress(layer_id, payload)
            print(f"[download] {layer_id}: {payload['percent']}% ({progress.get('current_sublayer')})")

    return callback


@celery_app.task(bind=True, max_retries=1)
def download_esri_layer_task(
    self,
    layer_id: str,
    output_formats: Optional[list[str]] = None,
    proxy_url: str = "",
    token: str = "",
):
    from app.infrastructure.services.esri_downloader import (
        DownloadCancelled, EsriDownloadError, download_service,
    )
    from app.core.config import settings

    with db.get_session() as session:
        repo = SyncLayerRepository(session)
        layer = repo.get_by_id(layer_id)
        if not layer:
            print(f"[download] Layer {layer_id} not found, aborting.")
            return
        if layer.layer_type not in ("esri_mapserver", "esri_featureserver"):
            print(f"[download] Layer {layer_id} has type {layer.layer_type}, aborting.")
            return
        current = repo.get_download_progress(layer_id) or {}
        if current.get("status") == "cancelled":
            print(f"[download] Task for {layer_id} cancelled before start, aborting.")
            return
        service_url = layer.tile_url_template
        repo.update_download_progress(layer_id, {
            "status": "processing",
            "percent": 0,
            "task_id": self.request.id,
            "started_at": datetime.now().isoformat(),
            "output_formats": output_formats,
        })

    dest_dir = Path(settings.DOWNLOAD_DIR) / layer_id
    progress_cb = _make_download_progress_callback(layer_id)
    try:
        manifest = download_service(
            service_url, dest_dir, progress_cb,
            output_formats=output_formats,
            proxy_url=proxy_url,
            token=token,
        )
        # store paths relative to DOWNLOAD_DIR so they map onto the /downloads mount
        for entry in manifest.get("sublayers", []):
            for key in ("geojson", "shapefile_zip", "geopackage", "kmz", "image", "world_file", "metadata"):
                if entry.get(key):
                    try:
                        entry[key] = str(Path(entry[key]).relative_to(settings.DOWNLOAD_DIR))
                    except ValueError:
                        pass  # keep absolute path if outside DOWNLOAD_DIR
        with db.get_session() as session:
            SyncLayerRepository(session).update_download_progress(layer_id, {
                "status": "done",
                "percent": 100,
                "task_id": self.request.id,
                "finished_at": datetime.now().isoformat(),
                "manifest": manifest,
            })
        print(f"[download] Layer {layer_id} download done.")
    except DownloadCancelled:
        with db.get_session() as session:
            SyncLayerRepository(session).update_download_progress(
                layer_id, {"status": "cancelled", "task_id": self.request.id}
            )
        print(f"[download] Layer {layer_id} download cancelled.")
    except Exception as exc:
        with db.get_session() as session:
            SyncLayerRepository(session).update_download_progress(layer_id, {
                "status": "failed",
                "task_id": self.request.id,
                "error": str(exc),
            })
        if isinstance(exc, EsriDownloadError):
            raise self.retry(exc=exc, countdown=10)
        raise


@celery_app.task(bind=True, max_retries=3)
def clean_up_task(self, layer_id: str):

    with db.get_session() as session:
        layer_repo = SyncLayerRepository(session)
        try:
            if not layer_repo.get_by_id(layer_id):
                return
        except Exception as exc:
            print(f"[tiling] Failed to clean up layer {layer_id}: {exc}")


@celery_app.task(bind=True, max_retries=2)
def generate_mbtiles_task(self, layer_id: str):
    from app.core.mbtiles import pack_tile_pyramid
    from app.core.config import settings

    with db.get_session() as session:
        layer = SyncLayerRepository(session).get_by_id(layer_id)
        if not layer:
            print(f"[mbtiles] Layer {layer_id} not found, aborting.")
            return
        # mvt -> pbf, everything raster -> png (matches the tilers' output)
        tile_format = "pbf" if layer.layer_type == "mvt" else "png"
        bounds = None
        if layer.bbox_west is not None:
            bounds = (layer.bbox_west, layer.bbox_south,
                      layer.bbox_east, layer.bbox_north)
        name = layer.filename
        SyncLayerRepository(session).update_mbtiles(
            layer_id, status="processing", progress={"percent": 0})

    tiles_dir = Path(settings.TILES_DIR) / layer_id
    out_path = Path(settings.MBTILES_DIR) / f"{layer_id}.mbtiles"

    def progress_cb(p: dict):
        with db.get_session() as s:
            SyncLayerRepository(s).update_mbtiles(layer_id, status="processing", progress=p)

    try:
        result = pack_tile_pyramid(
            tiles_dir=tiles_dir, output_path=out_path,
            tile_format=tile_format, name=name, bounds=bounds,
            progress_callback=progress_cb)
        with db.get_session() as s:
            SyncLayerRepository(s).update_mbtiles(
                layer_id, status="done",
                progress={"percent": 100, "tile_count": result["tile_count"],
                          "min_zoom": result["min_zoom"], "max_zoom": result["max_zoom"]},
                path=f"{layer_id}.mbtiles", size_bytes=result["size_bytes"])
        print(f"[mbtiles] {layer_id} done: {result['tile_count']} tiles, "
              f"{result['size_bytes']} bytes")
    except Exception as exc:
        with db.get_session() as s:
            SyncLayerRepository(s).update_mbtiles(
                layer_id, status="failed", progress={"error": str(exc)})
        raise self.retry(exc=exc, countdown=10)


@celery_app.task(bind=True, max_retries=2)
def discover_esri_service_task(self, layer_id: str, service_url: str):
    """Discover layers in an Esri service and save results to layer metadata."""
    from app.infrastructure.services.esri_client import EsriClient
    from app.infrastructure.services.esri_downloader import esri_service_base

    base_url = esri_service_base(service_url)
    if not base_url:
        raise Exception(f"Not a MapServer/FeatureServer URL: {service_url}")

    with db.get_session() as session:
        repo = SyncLayerRepository(session)
        repo.update_download_progress(layer_id, {
            "status": "processing", "percent": 0,
            "task_id": self.request.id, "discover": True,
        })

    try:
        client = EsriClient(base_url)
        service_info = client.get_service_info()
        render_only = client.is_render_only_service(service_info)
        layers = client.get_layers_from_service()

        layer_list = []
        for entry in layers:
            layer_id_sub = entry.get("id")
            if layer_id_sub is None:
                continue
            try:
                detail = client.get_layer_info(layer_id_sub)
            except Exception:
                continue
            geom = client.normalize_geometry_type(detail.get("geometryType"))
            if geom == "Unknown":
                geom = client.infer_geometry_type(layer_id_sub, detail)
            query_ok = client.is_query_supported(detail) or client.can_query_layer(layer_id_sub)
            layer_list.append({
                "id": layer_id_sub,
                "name": entry.get("name") or f"Layer {layer_id_sub}",
                "geometry_type": geom,
                "query_supported": query_ok,
            })

        result = {
            "service_type": "MapServer" if base_url.lower().endswith("mapserver") else "FeatureServer",
            "service_url": base_url,
            "render_only": render_only,
            "layers": layer_list,
            "total_queryable": sum(1 for l in layer_list if l["query_supported"]),
        }

        with db.get_session() as session:
            repo = SyncLayerRepository(session)
            layer = repo.get_by_id(layer_id)
            if layer:
                meta = dict(layer.file_metadata or {})
                meta["discover_result"] = result
                layer.file_metadata = meta
                _sa_attrs.flag_modified(layer, "file_metadata")
                session.add(layer)
                session.commit()

            repo.update_download_progress(layer_id, {
                "status": "done", "percent": 100,
                "task_id": self.request.id,
            })

        print(f"[discover] Layer {layer_id}: {len(layer_list)} layers found")
        return result

    except Exception as exc:
        with db.get_session() as session:
            SyncLayerRepository(session).update_download_progress(
                layer_id, {"status": "failed", "task_id": self.request.id, "error": str(exc)})
        raise self.retry(exc=exc, countdown=5)


@celery_app.task(bind=True, max_retries=2)
def estimate_esri_download_task(
    self, layer_id: str, output_formats: Optional[list[str]] = None,
    proxy_url: str = "", token: str = "",
):
    """Estimate download size for a saved Esri layer."""
    from app.infrastructure.services.esri_estimator import EsriEstimator
    from app.infrastructure.services.esri_downloader import esri_service_base

    with db.get_session() as session:
        repo = SyncLayerRepository(session)
        layer = repo.get_by_id(layer_id)
        if not layer:
            print(f"[estimate] Layer {layer_id} not found, aborting.")
            return None
        service_url = layer.tile_url_template
        if not esri_service_base(service_url):
            print(f"[estimate] Invalid Esri URL for layer {layer_id}")
            return None

    try:
        estimator = EsriEstimator(
            service_url, proxy_url=proxy_url, token=token,
        )
        result = estimator.estimate_service(output_formats=output_formats)

        with db.get_session() as session:
            repo = SyncLayerRepository(session)
            layer = repo.get_by_id(layer_id)
            if layer:
                meta = dict(layer.file_metadata or {})
                meta["estimate_result"] = result
                layer.file_metadata = meta
                _sa_attrs.flag_modified(layer, "file_metadata")
                session.add(layer)
                session.commit()

        print(f"[estimate] Layer {layer_id}: {result.get('total_features')} features, {result.get('total_chunks')} chunks")
        return result

    except Exception as exc:
        with db.get_session() as session:
            SyncLayerRepository(session).update_download_progress(
                layer_id, {"status": "failed", "task_id": self.request.id, "error": str(exc)})
        raise self.retry(exc=exc, countdown=5)
