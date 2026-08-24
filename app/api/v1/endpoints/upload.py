import asyncio
import os
import shutil
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
from app.domain.models import JobStatus, Layer, LayerType
from app.domain.schemas import (
    ChunkUploadResponse,
    JobStatusResponse,
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
from app.workers.tasks import process_tiling_task
from app.infrastructure.services.geoserver_service import GeoServerService
from app.infrastructure.services.bbox_extractor import extract_bbox_from_file
from app.infrastructure.services.file_service import FileService
from app.infrastructure.services.upload_artifact_client import UploadArtifactClient, UploadArtifactClientError
from app.domain.models import UploadSession

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

    if not session.final_path or not os.path.exists(session.final_path):
        raise HTTPException(status_code=400, detail="Assembled file not found on disk")

    await repo.set_status(upload_id, JobStatus.processing)

    layer_id = session.layer_id
    filename_without_ext = Path(session.filename).stem
    base_code = slugify(filename_without_ext)
    code = await generate_unique_code(base_code, layer_repo.code_exists)

    try:
        svc = GeoServerService(
            url=settings.GEOSERVER_URL,
            username=settings.GEOSERVER_USER,
            password=settings.GEOSERVER_PASSWORD,
            workspace=settings.GEOSERVER_WORKSPACE,
        )
        result = svc.publish_shp(session.final_path, code)
    except Exception as exc:
        await repo.set_status(upload_id, JobStatus.failed, str(exc))
        raise HTTPException(status_code=502, detail=f"GeoServer publish failed: {exc}")

    from app.infrastructure.services.bbox_extractor import extract_bbox_from_file, get_crs_from_file

    # bbox: prioritas dari file lokal, fallback hasil recalculate GeoServer
    bbox = extract_bbox_from_file(session.final_path) or result.get("bbox")
    crs_str = get_crs_from_file(session.final_path) if bbox else None

    geoserver_meta = {**result}
    if crs_str:
        geoserver_meta['crs'] = crs_str

    existing_layer = await layer_repo.get_by_id(layer_id)
    if existing_layer:
        await layer_repo.update(
            layer_id=layer_id,
            layer_type=LayerType.wms,
            tile_url_template=result["wms_url"],
            file_metadata={
                "geoserver": geoserver_meta,
                "layers": geoserver_meta.get("layer_name"),
            },
            bbox_west=bbox[0] if bbox else None,
            bbox_south=bbox[1] if bbox else None,
            bbox_east=bbox[2] if bbox else None,
            bbox_north=bbox[3] if bbox else None,
        )
    else:
        layer = Layer(
            id=layer_id,
            upload_session_id=upload_id,
            code=code,
            layer_type=LayerType.wms,
            filename=session.filename,
            file_type='external',
            tile_url_template=result["wms_url"],
            file_metadata={"geoserver": geoserver_meta, "layers": geoserver_meta.get("layer_name")},
            bbox_west=bbox[0] if bbox else None,
            bbox_south=bbox[1] if bbox else None,
            bbox_east=bbox[2] if bbox else None,
            bbox_north=bbox[3] if bbox else None,
        )
        await layer_repo.create(layer)

    await repo.set_status(upload_id, JobStatus.done)

    return {
        "message": "Layer published to GeoServer",
        "upload_id": upload_id,
        "layer_id": layer_id,
        "layer_name": result["layer_name"],
        "wms_url": result["wms_url"],
        "wfs_url": result["wfs_url"],
        "workspace": result["workspace"],
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

    if not session.final_path or not os.path.exists(session.final_path):
        raise HTTPException(status_code=400, detail="Assembled file not found on disk")

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

    # Copy GeoJSON or JSON as-is
    dest_path = layer_dir / f"data{file_ext}"
    shutil.copy2(session.final_path, dest_path)

    # Extract bbox
    bbox = extract_bbox_from_file(session.final_path)

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

    bbox = None
    if session.status == "done":
        layer_repo = LayerRepository(session_dep)
        layer = await layer_repo.get_by_id(session.layer_id)
        if layer and layer.bbox_west is not None:
            bbox = [layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north]

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
    )


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
