import math
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.domain.models import JobStatus, UploadSession
from app.domain.ports import ChunkStoragePort, UploadSessionRepositoryPort
from app.domain.upload_utils import allowed_file


class InitChunkedUploadUseCase:
    def __init__(self, repo: UploadSessionRepositoryPort, storage: ChunkStoragePort):
        self.repo = repo
        self.storage = storage

    async def execute(self, filename: str, total_size: int, output_format: str = "raster", max_zoom: int = None) -> UploadSession:
        file_type = allowed_file(filename)

        upload_id = str(uuid.uuid4())
        layer_id = str(uuid.uuid4())

        chunk_size = settings.CHUNK_UPLOAD_THRESHOLD
        total_chunks = math.ceil(total_size / chunk_size)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.UPLOAD_SESSION_EXPIRE_HOURS)

        self.storage.ensure_dir(upload_id)

        session = UploadSession(
            id=upload_id,
            filename=filename,
            file_type=file_type,
            layer_id=layer_id,
            total_size=total_size,
            received_bytes=0,
            status=JobStatus.pending,
            output_format=output_format,
            max_zoom=max_zoom,
            chunk_map={},
            total_chunks=total_chunks,
            uploaded_chunks=0,
            chunk_size=chunk_size,
            expires_at=expires_at,
        )
        return await self.repo.create(session)
