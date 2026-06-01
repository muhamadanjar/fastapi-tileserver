from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.core.config import settings
from app.domain.schemas import TilingJobResponse
from app.infrastructure.db.connection import get_async_session
from app.infrastructure.db.repository import UploadSessionRepository
from app.infrastructure.services.file_service import FileService
from app.usecases.process_upload import ProcessUploadUseCase

router = APIRouter()


def get_process_upload_usecase(
    session=Depends(get_async_session),
) -> ProcessUploadUseCase:
    return ProcessUploadUseCase(
        FileService(),
        UploadSessionRepository(session),
    )


@router.post("/upload-and-tile", response_model=TilingJobResponse)
async def upload_and_tile(
    file: UploadFile = File(...),
    output_format: str = Form("raster"),
    max_zoom: int = Form(None),
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
    return await use_case.execute(file, output_format=output_format, max_zoom=max_zoom)
