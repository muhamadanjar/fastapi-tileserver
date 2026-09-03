import asyncio
import os
import shutil
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from starlette.concurrency import run_in_threadpool
import uuid
from slugify import slugify

from app.core.exceptions import (
    ChunkUploadError,
    SessionAlreadyCompleteError,
    SessionNotFoundError,
    SessionExpiredError,
    UnsupportedFileFormatException,
)
from app.domain.models import ImportStatus, JobStatus, Layer, LayerType
from app.domain.schemas import (
    ChunkUploadResponse,
    JobStatusResponse,
    ShapefileImportedTable,
    ShapefileImportStatus,
    UploadInitRequest,
    UploadInitResponse,
    ArtifactTilingRequest,
    ArtifactTilingResponse,
)
from app.core.config import settings
from app.core.utils import generate_unique_code
from app.infrastructure.db.connection import get_async_session
from app.infrastructure.db.repository import UploadSessionRepository, LayerRepository
from app.usecases.init_chunked_upload import InitChunkedUploadUseCase
from app.usecases.receive_chunk import ReceiveChunkUseCase
from app.workers.tasks import process_tiling_task, publish_geoserver_task
from app.infrastructure.services.file_service import FileService
from app.infrastructure.services.upload_artifact_client import UploadArtifactClient, UploadArtifactClientError
from app.domain.models import UploadSession
from app.usecases.shapefile_import_dispatch import dispatch_shapefile_import

router = APIRouter(prefix="/uploads", tags=["uploads"])


def _get_repo(session=Depends(get_async_session)) -> UploadSessionRepository:
    return UploadSessionRepository(session)


def _get_layer_repo(session=Depends(get_async_session)) -> LayerRepository:
    return LayerRepository(session)


@router.post("/artifact", response_model=ArtifactTilingResponse, status_code=202)
async def create_artifact_tiling_job(
    body: ArtifactTilingRequest,
    repo: UploadSessionRepository = Depends(_get_repo),
):
    """Stage an available upload_api artifact for a later tiling request."""
    existing = await repo.get_by_artifact_handoff(body.handoff_id)
    if existing:
        if existing.artifact_id != body.artifact_id:
            raise HTTPException(status_code=409, detail="Handoff ID belongs to a different artifact")
        return ArtifactTilingResponse(
            upload_id=existing.id,
            layer_id=existing.layer_id,
            artifact_id=existing.artifact_id,
            status=existing.status,
            task_id=existing.celery_task_id,
        )

    upload_id = str(uuid.uuid4())
    layer_id = str(uuid.uuid4())
    client = UploadArtifactClient()
    print(upload_id)
    try:
        lease = await run_in_threadpool(
            client.acquire_lease,
            body.artifact_id,
            body.grant_id,
            body.handoff_id,
        )
        artifact = await run_in_threadpool(client.metadata, body.artifact_id)
        file_type = FileService.allowed_file(artifact["filename"])
    except (UploadArtifactClientError, UnsupportedFileFormatException) as exc:
        print("exc")
        if "lease" in locals():
            await run_in_threadpool(client.release_lease, body.artifact_id, lease["lease_id"])
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    upload = UploadSession(
        id=upload_id,
        filename=artifact["filename"],
        file_type=file_type,
        layer_id=layer_id,
        total_size=artifact["size_bytes"],
        received_bytes=artifact["size_bytes"],
        status=JobStatus.uploaded,
        final_path=f"artifact://{body.artifact_id}",
        output_format=body.output_format,
        max_zoom=body.max_zoom,
        chunk_map={},
        total_chunks=1,
        uploaded_chunks=1,
        chunk_size=artifact["size_bytes"],
        artifact_id=body.artifact_id,
        artifact_lease_id=lease["lease_id"],
        artifact_handoff_id=body.handoff_id,
    )
    try:
        await repo.create(upload)
    except Exception:
        await repo.delete(upload_id)
        await run_in_threadpool(client.release_lease, body.artifact_id, lease["lease_id"])
        raise
    return ArtifactTilingResponse(
        upload_id=upload_id,
        layer_id=layer_id,
        artifact_id=body.artifact_id,
        status=JobStatus.uploaded,
    )


@router.post("/init", response_model=UploadInitResponse, status_code=201)
async def init_upload(
    body: UploadInitRequest,
    repo: UploadSessionRepository = Depends(_get_repo),
):
    try:
        use_case = InitChunkedUploadUseCase(repo)
        session = await use_case.execute(body.filename, body.total_size, body.output_format, body.max_zoom)
    except UnsupportedFileFormatException as exc:
        raise HTTPException(status_code=415, detail=exc.message)

    return UploadInitResponse(
        upload_id=session.id,
        layer_id=session.layer_id,
        message="Chunked upload session created. Send chunks via POST /uploads/{upload_id}/{chunk_index}.",
        chunk_size=settings.CHUNK_UPLOAD_THRESHOLD,
        total_chunks=session.total_chunks,
    )


@router.post("/{upload_id}/tile")
async def trigger_tiling(
    upload_id: str,
    output_format: str = Query(None),
    max_zoom: int = Query(None),
    repo: UploadSessionRepository = Depends(_get_repo),
):
    session = await repo.get_by_id(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")

    allowed = {JobStatus.uploaded, JobStatus.failed}
    if session.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot trigger tiling from status '{session.status}'. Must be 'uploaded' or 'failed'.",
        )

    if not session.final_path or (
        not session.final_path.startswith("artifact://") and not os.path.exists(session.final_path)
    ):
        raise HTTPException(status_code=400, detail="Assembled file not found on disk")

    layer_id = session.layer_id
    file_type = session.file_type
    source_path = session.final_path
    fmt = output_format if output_format else session.output_format
    zoom = max_zoom if max_zoom is not None else session.max_zoom

    task = process_tiling_task.delay(
        upload_id=upload_id,
        layer_id=layer_id,
        file_type=file_type,
        source_path=source_path,
        output_format=fmt,
        max_zoom=zoom,
    )
    await repo.start_tiling(upload_id, task.id, fmt, zoom)

    return {
        "message": "Tiling started",
        "upload_id": upload_id,
        "layer_id": layer_id,
        "status": "processing",
    }


@router.post("/{upload_id}/geoserver")
async def publish_to_geoserver(
    upload_id: str,
    repo: UploadSessionRepository = Depends(_get_repo),
    layer_repo: LayerRepository = Depends(_get_layer_repo),
):
    session = await repo.get_by_id(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")

    filename_lower = session.filename.lower()
    if not (filename_lower.endswith('.shp') or filename_lower.endswith('.zip')):
        raise HTTPException(
            status_code=400,
            detail=f"GeoServer publish only supports .shp/.zip files, got '{session.filename}'",
        )

    allowed = {JobStatus.uploaded, JobStatus.failed}
    if session.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot publish from status '{session.status}'. Must be 'uploaded' or 'failed'.",
        )

    # Artifact handoff (upload-api) menyimpan final_path="artifact://<id>"; the worker
    # materializes it via upload-api. Local files must exist on disk (fast fail).
    if session.final_path and not session.final_path.startswith("artifact://") and not os.path.exists(session.final_path):
        raise HTTPException(status_code=400, detail="Assembled file not found on disk")

    # Duplicate-publish guard: the same file being published as WMS more than once
    # silently creates multiple GeoServer layers and "grey map" confusion. Reject a
    # re-publish of a source file that is already a published WMS layer.
    layer_name = f"{settings.GEOSERVER_WORKSPACE}:{slugify(Path(session.filename).stem)}"
    existing = await layer_repo.find_geoserver_layer_name(layer_name)
    if existing and existing.id != session.layer_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Source file is already published as WMS layer '{layer_name}' "
                f"(layer id {existing.id}). Duplicate publishes are blocked to avoid "
                "multi-layer style confusion."
            ),
        )

    await repo.set_status(upload_id, JobStatus.processing)

    layer_id = session.layer_id
    filename_without_ext = Path(session.filename).stem
    base_code = slugify(filename_without_ext)
    code = await generate_unique_code(base_code, layer_repo.code_exists)

    task = publish_geoserver_task.delay(upload_id=upload_id, layer_id=layer_id, code=code)
    await repo.set_task_id(upload_id, task.id)

    return {
        "message": "GeoServer publish started",
        "upload_id": upload_id,
        "layer_id": layer_id,
        "status": "processing",
    }


@router.post("/{upload_id}/save")
async def save_geojson(
    upload_id: str,
    repo: UploadSessionRepository = Depends(_get_repo),
    layer_repo: LayerRepository = Depends(_get_layer_repo),
):
    session = await repo.get_by_id(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")

    filename_lower = session.filename.lower()
    allowed_exts = ('.geojson', '.json', '.kml')
    if not any(filename_lower.endswith(ext) for ext in allowed_exts):
        raise HTTPException(
            status_code=400,
            detail=f"Save layer only supports .geojson/.json/.kml files, got '{session.filename}'",
        )

    allowed_statuses = {JobStatus.uploaded, JobStatus.failed}
    if session.status not in allowed_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot save from status '{session.status}'. Must be 'uploaded' or 'failed'.",
        )

    # Artifact handoff (upload-api): final_path="artifact://<id>", materiakan dulu (pola sama dengan publish geoserver).
    artifact_id = (
        session.final_path.removeprefix("artifact://")
        if session.final_path and session.final_path.startswith("artifact://")
        else None
    )
    if artifact_id is None and (not session.final_path or not os.path.exists(session.final_path)):
        raise HTTPException(status_code=400, detail="Assembled file not found on disk")
    source_ctx = (
        UploadArtifactClient().materialize(artifact_id, session.filename)
        if artifact_id
        else nullcontext(session.final_path)
    )

    is_kml = filename_lower.endswith('.kml')
    layer_id = session.layer_id

    # KML is pre-converted to GeoJSON by prepare_source_path(); always store as .geojson
    if is_kml or filename_lower.endswith('.geojson'):
        file_ext = '.geojson'
    else:
        file_ext = '.json'

    determined_layer_type = LayerType.kml if is_kml else LayerType.geojson

    # Create layer directory if it doesn't exist
    layer_dir = Path(settings.TILES_DIR) / layer_id
    layer_dir.mkdir(parents=True, exist_ok=True)

    dest_path = layer_dir / f"data{file_ext}"

    with source_ctx as materialized_source:
        # prepare_source_path menyamakan behavior dengan flow lokal: KML dikonversi ke GeoJSON.
        source_path, _ = FileService.prepare_source_path(Path(materialized_source))

        # Copy GeoJSON or JSON as-is
        shutil.copy2(source_path, dest_path)

        # Extract bbox
        bbox = extract_bbox_from_file(source_path)

    # Create or update layer
    tile_url_template = f"/{layer_id}/data{file_ext}"
    source_file_meta = {
        "filename": session.filename,
        "upload_id": upload_id,
        "file_type": 'vector',
        "uploaded_at": datetime.now().isoformat(),
    }
    existing_layer = await layer_repo.get_by_id(layer_id)

    if existing_layer:
        # Preserve existing metadata, merge source_file
        existing_meta = dict(existing_layer.file_metadata or {})
        existing_meta["source_file"] = source_file_meta
        await layer_repo.update(
            layer_id=layer_id,
            layer_type=determined_layer_type,
            tile_url_template=tile_url_template,
            file_metadata=existing_meta,
            bbox_west=bbox[0] if bbox else None,
            bbox_south=bbox[1] if bbox else None,
            bbox_east=bbox[2] if bbox else None,
            bbox_north=bbox[3] if bbox else None,
        )
        saved_layer = existing_layer
    else:
        saved_layer = Layer(
            id=layer_id,
            upload_session_id=upload_id,
            code=slugify(session.filename),
            layer_type=determined_layer_type,
            filename=session.filename,
            file_type='vector',
            tile_url_template=tile_url_template,
            file_metadata={"source_file": source_file_meta},
            bbox_west=bbox[0] if bbox else None,
            bbox_south=bbox[1] if bbox else None,
            bbox_east=bbox[2] if bbox else None,
            bbox_north=bbox[3] if bbox else None,
        )
        await layer_repo.create(saved_layer)

    await repo.set_status(upload_id, JobStatus.done)

    # Sync to CSW catalog
    from app.infrastructure.services.csw_sync import sync_layer
    await asyncio.to_thread(sync_layer, saved_layer)

    return {
        "message": "Layer saved",
        "upload_id": upload_id,
        "layer_id": layer_id,
        "layer_type": determined_layer_type,
        "tile_url_template": tile_url_template,
        "status": "done",
    }


@router.get("/{upload_id}/status", response_model=JobStatusResponse)
async def get_upload_status(
    upload_id: str,
    session_dep=Depends(get_async_session),
):
    repo = UploadSessionRepository(session_dep)
    session = await repo.get_by_id(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Upload session '{upload_id}' not found.")

    tile_url = None
    if session.status == "done":
        if session.output_format == "mvt":
            tile_url = f"/tiles/{session.layer_id}/{{z}}/{{x}}/{{y}}.pbf"
        else:
            tile_url = f"/tiles/{session.layer_id}/{{z}}/{{x}}/{{y}}.png"

    layer_repo = LayerRepository(session_dep)
    layer = await layer_repo.get_by_id(session.layer_id)
    bbox = None
    if session.status == "done" and layer and layer.bbox_west is not None:
        bbox = [layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north]

    postgis_metadata = ((layer.file_metadata or {}).get("postgis") or {}) if layer else {}
    imported_tables = [
        ShapefileImportedTable(
            schema=dataset.get("schema", "geodata"),
            table=dataset["table"],
            geometry_family=dataset.get("geometry_family"),
            row_count=int(dataset.get("row_count") or 0),
            bbox=dataset.get("bbox"),
        )
        for dataset in postgis_metadata.get("datasets", [])
        if isinstance(dataset, dict) and dataset.get("table")
    ]
    if not imported_tables and postgis_metadata.get("table"):
        imported_tables = [
            ShapefileImportedTable(
                schema=postgis_metadata.get("schema", "geodata"),
                table=postgis_metadata["table"],
                geometry_family=postgis_metadata.get("geometry_family"),
                row_count=int(postgis_metadata.get("row_count") or 0),
                bbox=postgis_metadata.get("bbox"),
            )
        ]

    progress_percent = round(session.uploaded_chunks / session.total_chunks * 100, 2) if session.total_chunks else 0.0
    chunk_map = session.chunk_map if session.status == "uploading" else None

    return JobStatusResponse(
        upload_id=session.id,
        layer_id=session.layer_id,
        status=session.status,
        received_bytes=session.received_bytes,
        total_size=session.total_size,
        uploaded_chunks=session.uploaded_chunks,
        total_chunks=session.total_chunks,
        progress_percent=progress_percent,
        chunk_map=chunk_map,
        error_message=session.error_message,
        tile_url_template=tile_url,
        bbox=bbox,
        import_process=ShapefileImportStatus(
            status=session.import_status,
            task_id=session.import_task_id,
            table=session.import_table_name,
            processed_rows=session.import_processed_rows,
            total_rows=session.import_total_rows,
            progress_percent=(
                round(session.import_processed_rows / session.import_total_rows * 100, 2)
                if session.import_total_rows
                else 0.0
            ),
            row_count=session.imported_row_count,
            tables=imported_tables,
            error=session.import_error,
            imported_at=session.imported_at,
        ),
    )


def _validate_shapefile_import_source(session: UploadSession) -> None:
    if not session.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="Only shapefile ZIP files can be imported")
    if session.status not in {JobStatus.uploaded, JobStatus.done}:
        raise HTTPException(
            status_code=409,
            detail=f"Upload is not ready with status '{session.status}'",
        )
    if not session.artifact_id and (
        not session.final_path or not Path(session.final_path).exists()
    ):
        raise HTTPException(status_code=404, detail="Source ZIP is no longer available")


@router.post("/{upload_id}/import", status_code=202)
async def start_shapefile_import(
    upload_id: str,
    repo: UploadSessionRepository = Depends(_get_repo),
):
    session = await repo.get_by_id(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")
    if session.import_status != ImportStatus.not_applicable:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot start import with status '{session.import_status}'",
        )
    _validate_shapefile_import_source(session)

    task_id = await dispatch_shapefile_import(session, repo)
    if not task_id:
        refreshed = await repo.get_by_id(upload_id)
        raise HTTPException(
            status_code=503,
            detail=refreshed.import_error if refreshed else "Failed to enqueue import",
        )
    return {
        "message": "Shapefile import queued",
        "upload_id": upload_id,
        "layer_id": session.layer_id,
        "task_id": task_id,
        "status": ImportStatus.pending,
    }


@router.post("/{upload_id}/import/retry", status_code=202)
async def retry_shapefile_import(
    upload_id: str,
    repo: UploadSessionRepository = Depends(_get_repo),
):
    session = await repo.get_by_id(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")
    if session.import_status != ImportStatus.failed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot retry import with status '{session.import_status}'",
        )
    _validate_shapefile_import_source(session)

    task_id = await dispatch_shapefile_import(session, repo)
    if not task_id:
        refreshed = await repo.get_by_id(upload_id)
        raise HTTPException(
            status_code=503,
            detail=refreshed.import_error if refreshed else "Failed to enqueue import",
        )
    return {
        "message": "Shapefile import re-queued",
        "upload_id": upload_id,
        "layer_id": session.layer_id,
        "task_id": task_id,
        "status": ImportStatus.pending,
    }


@router.delete("/{upload_id}/import")
async def cancel_shapefile_import(
    upload_id: str,
    repo: UploadSessionRepository = Depends(_get_repo),
):
    session = await repo.get_by_id(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")
    if session.import_status not in {ImportStatus.pending, ImportStatus.processing}:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel import with status '{session.import_status}'",
        )

    await repo.set_import_status(upload_id, ImportStatus.cancelled)
    if session.import_task_id:
        from app.workers.celery_app import celery_app

        celery_app.control.revoke(session.import_task_id, terminate=True, signal="SIGTERM")

    from app.infrastructure.db.connection import db
    from app.infrastructure.services.shapefile_import_service import drop_import_staging_table

    try:
        await run_in_threadpool(drop_import_staging_table, db.get_engine(), upload_id)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Import cancelled but staging cleanup failed: {exc}",
        ) from exc

    return {
        "message": "Shapefile import cancelled",
        "upload_id": upload_id,
        "status": ImportStatus.cancelled,
    }


@router.post("/{upload_id}/retry")
async def retry_tiling(
    upload_id: str,
    repo: UploadSessionRepository = Depends(_get_repo),
):
    session = await repo.get_by_id(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")
    if session.status not in (JobStatus.uploaded, JobStatus.failed):
        raise HTTPException(status_code=409, detail=f"Cannot retry session with status '{session.status}'")
    if not session.final_path or not Path(session.final_path).exists():
        raise HTTPException(status_code=404, detail="Source file missing from disk")

    process_tiling_task.delay(
        upload_id=upload_id,
        layer_id=session.layer_id,
        file_type=session.file_type,
        source_path=session.final_path,
        output_format=session.output_format,
        max_zoom=session.max_zoom,
    )
    return {"message": "Tiling re-queued", "upload_id": upload_id, "layer_id": session.layer_id}


@router.post("/{upload_id}/cancel")
async def cancel_tiling(
    upload_id: str,
    repo: UploadSessionRepository = Depends(_get_repo),
):
    session = await repo.get_by_id(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")

    cancellable = {JobStatus.uploaded, JobStatus.pending, JobStatus.processing}
    if session.status not in cancellable:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel from status '{session.status}'."
        )

    if session.celery_task_id:
        from app.workers.celery_app import celery_app
        celery_app.control.revoke(session.celery_task_id, terminate=True, signal='SIGTERM')

    await repo.set_status(upload_id, JobStatus.cancelled)

    return APIResponse.success(
        message="Tiling cancelled",
        data={"upload_id": upload_id, "status": "cancelled"}
    )


@router.post("/{upload_id}/{chunk_index}", response_model=ChunkUploadResponse)
async def receive_chunk(
    upload_id: str,
    chunk_index: int,
    request: Request,
    repo: UploadSessionRepository = Depends(_get_repo),
):
    chunk_data = await request.body()
    if not chunk_data:
        raise HTTPException(status_code=400, detail="Empty request body.")

    try:
        use_case = ReceiveChunkUseCase(repo)
        return await use_case.execute(upload_id, chunk_index, chunk_data)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    except SessionAlreadyCompleteError as exc:
        raise HTTPException(status_code=409, detail=exc.message)
    except SessionExpiredError as exc:
        raise HTTPException(status_code=410, detail=exc.message)
    except ChunkUploadError as exc:
        raise HTTPException(status_code=400, detail=exc.message)
