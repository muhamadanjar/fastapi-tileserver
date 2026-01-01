
import shutil
import zipfile
import uuid
from pathlib import Path
from fastapi import UploadFile
from typing import Optional, Tuple
from app.core.config import settings
from app.core.exceptions import FileSaveError, UnsupportedFileFormatException

class FileService:
    @staticmethod
    def get_unique_filename(filename: str) -> str:
        ext = Path(filename).suffix
        name_only = Path(filename).stem
        unique_id = str(uuid.uuid4())[:8]
        return f"{unique_id}_{name_only}{ext}"

    @staticmethod
    def allowed_file(filename: str) -> str:
        ext = Path(filename).suffix.lower()
        if ext in {'.shp', '.geojson', '.json', '.gpkg', '.kml', '.zip'}:
            return 'vector'
        elif ext in {'.tif', '.tiff', '.img', '.png', '.jpg'}:
            return 'raster'
        return None

    async def save_upload(self, file: UploadFile) -> Tuple[Path, str]:
        """
        Saves the uploaded file. If it's a ZIP, extracts it.
        Returns (Path to source for tiling, file_type).
        For ZIP (SHP), returns path to the folder containing extracted files.
        """
        file_type = self.allowed_file(file.filename)
        if not file_type:
            raise UnsupportedFileFormatException(file.filename)

        unique_name = self.get_unique_filename(file.filename)
        save_path = settings.UPLOAD_DIR / unique_name
        
        try:
            with open(save_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        except Exception as e:
            raise FileSaveError(str(e))

        # Handle ZIP for Shapefiles
        if save_path.suffix.lower() == '.zip':
            extract_dir = settings.UPLOAD_DIR / save_path.stem
            extract_dir.mkdir(exist_ok=True)
            
            try:
                with zipfile.ZipFile(save_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
            except zipfile.BadZipFile:
                 # Remove corrupt file
                 save_path.unlink()
                 raise FileSaveError("Invalid ZIP file")
            
            # Clean up zip file ?? Maybe keep it for reference? 
            # Let's keep it for now.
            
            # Identify the .shp file inside the extracted directory
            shp_files = list(extract_dir.glob("**/*.shp"))
            if not shp_files:
                 # Clean up
                 shutil.rmtree(extract_dir)
                 save_path.unlink()
                 raise FileSaveError("ZIP archive does not contain a .shp file.")
            
            # Return the path to the SHP file (or directory if we want flexibility, but Tiler expects a file path usually)
            # Actually, VectorTiler using geopandas needs the path to the .shp file.
            return shp_files[0], 'vector'
            
        return save_path, file_type
