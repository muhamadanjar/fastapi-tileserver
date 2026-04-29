from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.core.config import settings
from app.domain.schemas import TilingJobResponse
from app.infrastructure.broker.publisher import RabbitMQPublisher
from app.infrastructure.db.connection import get_async_session
from app.infrastructure.db.repository import UploadSessionRepository
from app.infrastructure.services.file_service import FileService
from app.usecases.process_upload import ProcessUploadUseCase

router = APIRouter()


def _get_publisher(request: Request) -> RabbitMQPublisher:
    return request.app.state.publisher


def get_process_upload_usecase(
    request: Request,
    session=Depends(get_async_session),
) -> ProcessUploadUseCase:
    return ProcessUploadUseCase(
        FileService(),
        _get_publisher(request),
        UploadSessionRepository(session),
    )


@router.post("/upload-and-tile", response_model=TilingJobResponse)
async def upload_and_tile(
    file: UploadFile = File(...),
    use_case: ProcessUploadUseCase = Depends(get_process_upload_usecase),
):
    if file.size and file.size > settings.CHUNK_UPLOAD_THRESHOLD:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large for direct upload "
                f"(max {settings.CHUNK_UPLOAD_THRESHOLD} bytes). "
                "Use chunked upload: POST /api/v1/uploads/init"
            ),
        )
    return await use_case.execute(file)
