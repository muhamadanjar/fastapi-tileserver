from pathlib import Path
from datetime import datetime
from sqlalchemy.orm import attributes as _sa_attrs

from app.workers.celery_app import celery_app
from app.infrastructure.db.connection import db
from app.infrastructure.db.repository import SyncUploadSessionRepository, SyncLayerRepository
from app.infrastructure.services.tiling_service import TilingService
from app.infrastructure.services.csw_sync import sync_layer
from app.domain.models import JobStatus, Layer
from app.core.utils import slugify, generate_unique_code_sync


def _make_progress_callback(layer_id: str):
    state = {"last": None}

    def callback(progress: dict) -> None:
        payload = {**progress, "status": "processing"}
        state["last"] = payload
        try:
            with db.get_session() as session:
                SyncLayerRepository(session).update_progress(layer_id, payload)
                print(f"[progress] Updated {layer_id}: {payload.get('percent', 0)}%")
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


@celery_app.task(bind=True, max_retries=3)
def process_tiling_task(self, upload_id: str, layer_id: str, file_type: str, source_path: str, output_format: str = "raster", max_zoom: int = None):
    with db.get_session() as session:
        repo = SyncUploadSessionRepository(session)
        current = repo.get_by_id(upload_id)
        if current and current.status == JobStatus.cancelled:
            print(f"[tiling] Task {upload_id} cancelled before start, aborting.")
            return
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

        progress_cb, finalize_progress = _make_progress_callback(layer_id)
        bounds = TilingService.process_tiling(file_type, Path(source_path), layer_id, output_format=output_format, style=style, progress_callback=progress_cb, max_zoom=max_zoom)
        finalize_progress()
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
        if not isinstance(exc, SystemExit):
            raise self.retry(exc=exc, countdown=5)


@celery_app.task(bind=True, max_retries=3)
def clean_up_task(self, layer_id: str):
    
    with db.get_session() as session:
        layer_repo = SyncLayerRepository(session)
        try:
            if not layer_repo.get_by_id(layer_id):
                return
        except Exception as exc:
            print(f"[tiling] Failed to clean up layer {layer_id}: {exc}")
