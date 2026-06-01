from datetime import datetime, timezone

from app.core.config import settings
from app.core.exceptions import (
    ChunkUploadError,
    SessionAlreadyCompleteError,
    SessionNotFoundError,
    SessionExpiredError,
)
from app.domain.models import JobStatus
from app.domain.schemas import ChunkUploadResponse
from app.infrastructure.db.repository import UploadSessionRepository
from app.infrastructure.services.file_service import FileService
from app.infrastructure.storage.chunk_storage import ChunkStorage
from app.workers.tasks import process_tiling_task


class ReceiveChunkUseCase:
    def __init__(self, repo: UploadSessionRepository):
        self.repo = repo

    async def execute(
        self,
        upload_id: str,
        chunk_index: int,
        chunk_data: bytes,
    ) -> ChunkUploadResponse:
        session = await self.repo.get_by_id(upload_id)
        if not session:
            raise SessionNotFoundError(upload_id)

        if session.status in (JobStatus.done, JobStatus.processing):
            raise SessionAlreadyCompleteError(upload_id)

        if session.status == JobStatus.expired:
            raise SessionExpiredError(upload_id)

        if session.expires_at and session.expires_at <= datetime.now(timezone.utc):
            await self.repo.mark_expired(upload_id)
            raise SessionExpiredError(upload_id)

        start = chunk_index * session.chunk_size
        end = min(start + session.chunk_size, session.total_size)
        expected_size = end - start

        if len(chunk_data) != expected_size:
            raise ChunkUploadError(
                f"Chunk {chunk_index}: expected {expected_size} bytes, got {len(chunk_data)}."
            )

        storage = ChunkStorage()
        storage.write_chunk(upload_id, chunk_data, start)

        new_chunk_map = dict(session.chunk_map or {})
        new_chunk_map[str(chunk_index)] = len(chunk_data)
        new_uploaded_chunks = len(new_chunk_map)
        new_received_bytes = sum(new_chunk_map.values())

        await self.repo.update_chunk_map(
            upload_id, chunk_index, len(chunk_data), new_uploaded_chunks, new_received_bytes
        )

        is_complete = new_uploaded_chunks >= session.total_chunks

        if is_complete:
            unique_name = FileService.get_unique_filename(session.filename)
            assembled_path = settings.UPLOAD_DIR / unique_name

            try:
                storage.assemble_chunks(upload_id, assembled_path)
                source_path, _ = FileService.prepare_source_path(assembled_path)
            except Exception as exc:
                storage.cleanup_chunks(upload_id)
                await self.repo.set_status(upload_id, JobStatus.failed, str(exc))
                raise ChunkUploadError(f"Assembly failed: {exc}") from exc

            await self.repo.mark_complete(upload_id, str(source_path))
            process_tiling_task.delay(
                upload_id=upload_id,
                layer_id=session.layer_id,
                file_type=session.file_type,
                source_path=str(source_path),
                output_format=session.output_format,
            )

        progress_percent = round(new_uploaded_chunks / session.total_chunks * 100, 2)

        tile_url = None
        if is_complete:
            if session.output_format == "mvt":
                tile_url = f"/tiles/{session.layer_id}/{{z}}/{{x}}/{{y}}.pbf"
            else:
                tile_url = f"/tiles/{session.layer_id}/{{z}}/{{x}}/{{y}}.png"

        return ChunkUploadResponse(
            upload_id=upload_id,
            received_bytes=new_received_bytes,
            total_size=session.total_size,
            uploaded_chunks=new_uploaded_chunks,
            total_chunks=session.total_chunks,
            progress_percent=progress_percent,
            is_complete=is_complete,
            layer_id=session.layer_id if is_complete else None,
            tile_url_template=tile_url,
        )
