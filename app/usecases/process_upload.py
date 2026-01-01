
from fastapi import UploadFile, BackgroundTasks
from app.infrastructure.services.file_service import FileService
from app.infrastructure.services.tiling_service import TilingService
from app.domain.schemas import TilingJobResponse
from app.core.exceptions import TileServerException
from pathlib import Path

class ProcessUploadUseCase:
    def __init__(self, file_service: FileService, background_tasks: BackgroundTasks):
        self.file_service = file_service
        self.background_tasks = background_tasks

    async def execute(self, file: UploadFile) -> TilingJobResponse:
        # 1. Save and potentially extract file
        source_path, file_type = await self.file_service.save_upload(file)
        
        # 2. Prepare Layer ID (using parent folder name for zips or filename for single files)
        # Using the unique part of the source filename (or directory)
        layer_id = source_path.stem
        if file_type == 'vector' and source_path.parent.name.startswith(f"{source_path.stem}"): 
             # Refers to extracted zip folder naming convention if needed, 
             # but FileService returns specific .shp path. 
             # Let's clean up layer_id to be the unique identifier we generated.
             # FileService generates unique_id_filename.ext
             # We want unique_id_filename as layer_id
             pass

        # 3. Schedule Tiling in Background
        # Note: We pass the path as string or Path object. TilingService expects Path for correctness but we used str in some places.
        # Let's ensure TilingService handles it.
        self.background_tasks.add_task(
            TilingService.process_tiling, 
            file_type, 
            source_path, 
            layer_id
        )

        return TilingJobResponse(
            message="File uploaded successfully, tiling process started.",
            file_type=file_type,
            layer_id=layer_id,
            tile_url_template=f"/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png"
        )
