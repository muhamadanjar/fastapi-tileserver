import uuid
from pathlib import Path

from app.core.config import settings
from app.domain.models import JobStatus, UploadSession
from app.infrastructure.db.repository import UploadSessionRepository
from app.infrastructure.services.file_service import FileService
from app.infrastructure.storage.chunk_storage import ChunkStorage


class InitChunkedUploadUseCase:
    def __init__(self, repo: UploadSessionRepository):
        self.repo = repo

    async def execute(self, filename: str, total_size: int, output_format: str = "raster") -> UploadSession:
        file_type = FileService.allowed_file(filename)

        upload_id = str(uuid.uuid4())
        layer_id = str(uuid.uuid4())
        unique_name = FileService.get_unique_filename(filename)

        ChunkStorage(upload_id).ensure_dir()

        session = UploadSession(
            id=upload_id,
            filename=filename,
            file_type=file_type,
            layer_id=layer_id,
            total_size=total_size,
            received_bytes=0,
            status=JobStatus.pending,
            output_format=output_format,
        )
        return await self.repo.create(session)
