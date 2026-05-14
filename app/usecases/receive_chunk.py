import math
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import ChunkUploadError, SessionAlreadyCompleteError, SessionNotFoundError
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
        range_start: int,
        range_end: int,
        total_size: int,
        chunk_data: bytes,
    ) -> ChunkUploadResponse:
        session = await self.repo.get_by_id(upload_id)
        if not session:
            raise SessionNotFoundError(upload_id)

        if session.status in (JobStatus.done, JobStatus.processing):
            raise SessionAlreadyCompleteError(upload_id)

        actual_chunk_size = range_end - range_start + 1
        if len(chunk_data) != actual_chunk_size:
            raise ChunkUploadError(
                f"Chunk body size {len(chunk_data)} does not match "
                f"Content-Range {range_start}-{range_end}."
            )

        chunk_index = range_start // settings.CHUNK_UPLOAD_THRESHOLD
        storage = ChunkStorage(upload_id)
        storage.write_chunk(chunk_index, chunk_data)

        new_received = range_end + 1
        await self.repo.update_received_bytes(upload_id, new_received)

        is_complete = new_received >= total_size

        if is_complete:
            part_count = math.ceil(total_size / settings.CHUNK_UPLOAD_THRESHOLD)
            unique_name = FileService.get_unique_filename(session.filename)
            assembled_path = settings.UPLOAD_DIR / unique_name

            try:
                storage.assemble(assembled_path, part_count)
                source_path, _ = FileService.prepare_source_path(assembled_path)
            except Exception as exc:
                storage.cleanup()
                await self.repo.set_status(upload_id, JobStatus.failed, str(exc))
                raise ChunkUploadError(f"Assembly failed: {exc}") from exc

            await self.repo.mark_complete(upload_id, str(source_path))
            process_tiling_task.delay(
                upload_id=upload_id,
                layer_id=session.layer_id,
                file_type=session.file_type,
                source_path=str(source_path),
            )

        return ChunkUploadResponse(
            upload_id=upload_id,
            received_bytes=new_received,
            total_size=total_size,
            is_complete=is_complete,
            layer_id=session.layer_id if is_complete else None,
            tile_url_template=(
                f"/tiles/{session.layer_id}/{{z}}/{{x}}/{{y}}.png"
                if is_complete
                else None
            ),
        )
