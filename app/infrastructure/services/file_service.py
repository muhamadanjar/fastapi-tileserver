import shutil
import zipfile
import uuid
from pathlib import Path
from typing import Tuple

from fastapi import UploadFile

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
        """Returns file_type ('vector' or 'raster') or raises UnsupportedFileFormatException."""
        ext = Path(filename).suffix.lower()
        if ext in {".shp", ".geojson", ".json", ".gpkg", ".kml", ".zip"}:
            return "vector"
        elif ext in {".tif", ".tiff", ".img", ".png", ".jpg"}:
            return "raster"
        raise UnsupportedFileFormatException(filename)

    @staticmethod
    def extract_zip(zip_path: Path) -> Path:
        """
        Extracts a ZIP shapefile archive and returns the path to the .shp file inside.
        Cleans up on failure. The ZIP file is kept for reference.
        """
        extract_dir = settings.UPLOAD_DIR / zip_path.stem
        extract_dir.mkdir(exist_ok=True)

        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)
        except zipfile.BadZipFile:
            zip_path.unlink(missing_ok=True)
            raise FileSaveError("Invalid ZIP file")

        shp_files = list(extract_dir.glob("**/*.shp"))
        if not shp_files:
            shutil.rmtree(extract_dir)
            zip_path.unlink(missing_ok=True)
            raise FileSaveError("ZIP archive does not contain a .shp file.")

        return shp_files[0]

    @staticmethod
    def prepare_source_path(saved_path: Path) -> Tuple[Path, str]:
        """
        Given a saved file path, returns the actual tiling source path and file_type.
        For ZIP files, extracts and returns the .shp path.
        Reusable by both direct upload and chunked assembly flows.
        """
        file_type = FileService.allowed_file(saved_path.name)
        if saved_path.suffix.lower() == ".zip":
            return FileService.extract_zip(saved_path), "vector"
        return saved_path, file_type

    async def save_upload(self, file: UploadFile) -> Tuple[Path, str]:
        """Saves the uploaded file and returns (source_path_for_tiling, file_type)."""
        FileService.allowed_file(file.filename)

        unique_name = self.get_unique_filename(file.filename)
        save_path = settings.UPLOAD_DIR / unique_name

        try:
            with open(save_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        except Exception as e:
            raise FileSaveError(str(e))

        return self.prepare_source_path(save_path)
