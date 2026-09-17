"""Layer-type detection for /uploads/{id}/save (see docs/plans/upload-layer-type-detection.md)."""

from app.domain.models import LayerType
from app.domain.upload_utils import save_layer_type


def test_save_layer_type_mapping():
    assert save_layer_type("jalan.geojson") == (LayerType.geojson, ".geojson")
    assert save_layer_type("jalan.JSON") == (LayerType.geojson, ".json")
    assert save_layer_type("taman.kml") == (LayerType.kml, ".geojson")
    assert save_layer_type("jalan.shp.zip") == (LayerType.shp, ".zip")
    assert save_layer_type("JALAN.ZIP") == (LayerType.shp, ".zip")