"""Layer-type detection for /uploads/{id}/save (see docs/plans/upload-layer-type-detection.md)."""

from app.domain.models import LayerType
from app.infrastructure.services.file_service import FileService


def test_save_layer_type_mapping():
    assert FileService.save_layer_type("jalan.geojson") == (LayerType.geojson, ".geojson")
    assert FileService.save_layer_type("jalan.JSON") == (LayerType.geojson, ".json")
    assert FileService.save_layer_type("taman.kml") == (LayerType.kml, ".geojson")
    assert FileService.save_layer_type("jalan.shp.zip") == (LayerType.shp, ".zip")
    assert FileService.save_layer_type("JALAN.ZIP") == (LayerType.shp, ".zip")