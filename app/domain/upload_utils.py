"""Pure filename/path/type helpers shared by upload flows (infra-agnostic)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Tuple

from app.core.exceptions import FileSaveError, UnsupportedFileFormatException


def get_unique_filename(filename: str) -> str:
    ext = Path(filename).suffix
    name_only = Path(filename).stem
    unique_id = str(uuid.uuid4())[:8]
    return f"{unique_id}_{name_only}{ext}"


def allowed_file(filename: str) -> str:
    """Returns file_type ('vector' or 'raster') or raises UnsupportedFileFormatException."""
    ext = Path(filename).suffix.lower()
    if ext in {".geojson", ".json", ".gpkg", ".kml", ".zip"}:
        return "vector"
    elif ext in {".tif", ".tiff", ".img", ".png", ".jpg"}:
        return "raster"
    raise UnsupportedFileFormatException(filename)


def save_layer_type(filename_lower: str):
    """Map a save-eligible filename to (LayerType, stored file extension).

    KML is pre-converted to GeoJSON by prepare_source_path() but keeps the
    kml layer type; shapefile ZIPs are stored as-is (never extracted).
    """
    from app.domain.models import LayerType

    filename_lower = filename_lower.lower()

    if filename_lower.endswith(".kml"):
        return LayerType.kml, ".geojson"
    if filename_lower.endswith(".zip"):
        return LayerType.shp, ".zip"
    if filename_lower.endswith(".geojson"):
        return LayerType.geojson, ".geojson"
    return LayerType.geojson, ".json"


def convert_kml_to_geojson(kml_path: Path) -> Path:
    """Convert KML to GeoJSON, save as .geojson, return new path."""
    try:
        import geopandas as gpd

        gdf = gpd.read_file(kml_path, driver="KML")
        geojson_data = json.loads(gdf.to_json())

        geojson_path = kml_path.with_suffix(".geojson")
        with open(geojson_path, "w") as f:
            json.dump(geojson_data, f)

        kml_path.unlink(missing_ok=True)
        return geojson_path
    except Exception as e:
        raise FileSaveError(f"KML conversion failed: {str(e)}")


def prepare_source_path(saved_path: Path) -> Tuple[Path, str]:
    """
    Given a saved file path, returns the actual tiling source path and file_type.
    ZIP files stay intact so validation and extraction happen in the Celery
    import worker rather than blocking the upload request.
    For KML files, converts to GeoJSON and returns .geojson path.
    Reusable by both direct upload and chunked assembly flows.
    """
    file_type = allowed_file(saved_path.name)
    if saved_path.suffix.lower() == ".kml":
        geojson_path = convert_kml_to_geojson(saved_path)
        return geojson_path, "vector"
    return saved_path, file_type