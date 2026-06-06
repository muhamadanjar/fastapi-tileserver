import uuid

from fastapi import UploadFile

from app.domain.models import UploadSession, JobStatus
from app.domain.schemas import TilingJobResponse
from app.infrastructure.db.repository import UploadSessionRepository
from app.infrastructure.services.file_service import FileService


class ProcessUploadUseCase:
    def __init__(
        self,
        file_service: FileService,
        repo: UploadSessionRepository,
    ):
        self.file_service = file_service
        self.repo = repo

    async def execute(self, file: UploadFile, output_format: str = "raster", max_zoom: int = None) -> TilingJobResponse:
        source_path, file_type = await self.file_service.save_upload(file)
        layer_id = str(uuid.uuid4())
        upload_id = str(uuid.uuid4())

        session = UploadSession(
            id=upload_id,
            filename=file.filename,
            file_type=file_type,
            layer_id=layer_id,
            total_size=file.size or 0,
            received_bytes=file.size or 0,
            status=JobStatus.uploaded,
            final_path=str(source_path),
            output_format=output_format,
            max_zoom=max_zoom,
        )
        await self.repo.create(session)

        return TilingJobResponse(
            message="File uploaded. POST /uploads/{upload_id}/tile to start tiling.",
            upload_id=upload_id,
            file_type=file_type,
            layer_id=layer_id,
            tile_url_template=None,
        )
