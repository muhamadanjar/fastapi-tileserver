import shutil
import zipfile
from pathlib import Path
from typing import Tuple

from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import FileSaveError
from app.domain.upload_utils import allowed_file, get_unique_filename, prepare_source_path


class FileService:
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

    async def save_upload(self, file: UploadFile) -> Tuple[Path, str]:
        """Saves the uploaded file and returns (source_path_for_tiling, file_type)."""
        allowed_file(file.filename)

        unique_name = get_unique_filename(file.filename)
        save_path = settings.UPLOAD_DIR / unique_name

        try:
            with open(save_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        except Exception as e:
            raise FileSaveError(str(e))

        return prepare_source_path(save_path)