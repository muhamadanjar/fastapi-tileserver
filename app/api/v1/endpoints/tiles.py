
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, Depends
from app.usecases.process_upload import ProcessUploadUseCase
from app.domain.schemas import TilingJobResponse
from app.infrastructure.services.file_service import FileService

router = APIRouter()

def get_process_upload_usecase(background_tasks: BackgroundTasks) -> ProcessUploadUseCase:
    return ProcessUploadUseCase(FileService(), background_tasks)

@router.post("/upload-and-tile", response_model=TilingJobResponse)
async def upload_and_tile(
    file: UploadFile = File(...),
    use_case: ProcessUploadUseCase = Depends(get_process_upload_usecase)
):
    return await use_case.execute(file)
