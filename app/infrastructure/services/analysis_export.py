"""File I/O service for overlay analysis results."""

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

import geopandas as gpd


class AnalysisExportService:
    """Handles reading/writing/deleting analysis result files."""

    def __init__(self, upload_dir: Path):
        self.upload_dir = upload_dir

    def save_geojson(self, gdf: "gpd.GeoDataFrame", result_id: str) -> str:
        """Save GeoDataFrame as GeoJSON. Returns file path."""
        output_dir = os.path.join(self.upload_dir, result_id)
        os.makedirs(output_dir, exist_ok=True)
        result_file = os.path.join(output_dir, "result.geojson")
        gdf.to_file(result_file, driver="GeoJSON")
        return result_file

    def delete_result(self, file_path: str) -> None:
        """Delete a result file and its parent directory."""
        if file_path and os.path.exists(file_path):
            parent_dir = os.path.dirname(file_path)
            if parent_dir:
                shutil.rmtree(parent_dir, ignore_errors=True)

    def get_geojson_path(self, file_path: str) -> Optional[Path]:
        """Return Path to existing GeoJSON result file, or None."""
        if file_path and os.path.exists(file_path):
            return Path(file_path)
        return None

    def export_shp_zip(self, file_path: str) -> Optional[Path]:
        """Convert GeoJSON result to zipped Shapefile. Returns zip path."""
        if not file_path or not os.path.exists(file_path):
            return None
        gdf = gpd.read_file(file_path)
        tmp_dir = tempfile.mkdtemp()
        shp_path = os.path.join(tmp_dir, "result.shp")
        gdf.to_file(shp_path, driver="ESRI Shapefile")
        zip_path = os.path.join(tmp_dir, "result.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in os.listdir(tmp_dir):
                if f.endswith((".shp", ".shx", ".dbf", ".prj")):
                    zf.write(os.path.join(tmp_dir, f), f)
        return Path(zip_path)
