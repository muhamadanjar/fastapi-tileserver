import math
import uuid
from datetime import datetime, timezone, timedelta
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

        chunk_size = settings.CHUNK_UPLOAD_THRESHOLD
        total_chunks = math.ceil(total_size / chunk_size)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.UPLOAD_SESSION_EXPIRE_HOURS)

        ChunkStorage().ensure_dir(upload_id)

        session = UploadSession(
            id=upload_id,
            filename=filename,
            file_type=file_type,
            layer_id=layer_id,
            total_size=total_size,
            received_bytes=0,
            status=JobStatus.pending,
            output_format=output_format,
            chunk_map={},
            total_chunks=total_chunks,
            uploaded_chunks=0,
            chunk_size=chunk_size,
            expires_at=expires_at,
        )
        return await self.repo.create(session)
