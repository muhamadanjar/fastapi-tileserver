from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.exceptions import (
    ChunkUploadError,
    SessionAlreadyCompleteError,
    SessionNotFoundError,
    SessionExpiredError,
    UnsupportedFileFormatException,
)
from app.domain.schemas import (
    ChunkUploadResponse,
    JobStatusResponse,
    UploadInitRequest,
    UploadInitResponse,
)
from app.core.config import settings
from app.infrastructure.db.connection import get_async_session
from app.infrastructure.db.repository import UploadSessionRepository, LayerRepository
from app.usecases.init_chunked_upload import InitChunkedUploadUseCase
from app.usecases.receive_chunk import ReceiveChunkUseCase
from app.workers.tasks import process_tiling_task

router = APIRouter(prefix="/uploads", tags=["uploads"])


def _get_repo(session=Depends(get_async_session)) -> UploadSessionRepository:
    return UploadSessionRepository(session)


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
    if session.status not in ("pending", "failed"):
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
