from types import SimpleNamespace

from app.usecases import getinfo_layer
from app.usecases.getinfo_layer import QueryLayerFeaturesUseCase


class FakeResponse:
    status_code = 200

    @staticmethod
    def json():
        return {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {"name": "Road A"}}],
        }


def test_manual_geoserver_getmap_url_becomes_clean_getfeatureinfo(monkeypatch):
    captured = {}

    def fake_get(url, params, timeout):
        captured.update({"url": url, "params": params, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(getinfo_layer.requests, "get", fake_get)
    layer = SimpleNamespace(
        tile_url_template=(
            "https://geo.example.com/geoserver/workspace/wms?"
            "SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&"
            "LAYERS=workspace%3Aroads&BBOX=-7,106,-6,107&"
            "CRS=EPSG%3A4326&WIDTH=256&HEIGHT=256"
        ),
        file_metadata={"LAYERS": "workspace:roads"},
    )

    result = QueryLayerFeaturesUseCase(None, None)._query_wms(layer, 106.8, -6.2)

    assert result.count == 1
    assert result.features == [{"name": "Road A"}]
    assert captured["url"] == "https://geo.example.com/geoserver/workspace/wms"
    assert captured["params"]["request"] == "GetFeatureInfo"
    assert captured["params"]["layers"] == "workspace:roads"
    assert captured["params"]["query_layers"] == "workspace:roads"
    assert captured["params"]["info_format"] == "application/json"
    assert captured["params"]["i"] == 256
    assert captured["params"]["j"] == 256
    assert captured["params"]["crs"] == "EPSG:4326"
    assert not any(key.isupper() for key in captured["params"])
