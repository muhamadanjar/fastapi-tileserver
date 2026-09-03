from types import SimpleNamespace

from app.api.v1.endpoints import layers
from app.usecases.get_layer_fields import GetLayerFieldsUseCase


def test_wms_capabilities_are_normalized_to_available_layers(monkeypatch):
    xml = b"""<?xml version=\"1.0\"?>
    <WMS_Capabilities xmlns=\"http://www.opengis.net/wms\">
      <Capability><Layer><Title>Root</Title>
        <Layer><Name>workspace:roads</Name><Title>Road network</Title></Layer>
        <Layer><Name>workspace:parcels</Name><Title>Parcels</Title></Layer>
      </Layer></Capability>
    </WMS_Capabilities>"""

    monkeypatch.setattr(
        "requests.get",
        lambda *args, **kwargs: SimpleNamespace(status_code=200, content=xml),
    )

    assert layers._fetch_wms_layers("https://maps.example.test/wms") == [
        {"id": "workspace:roads", "name": "Road network"},
        {"id": "workspace:parcels", "name": "Parcels"},
    ]


def test_wms_field_lookup_uses_the_selected_named_layer(monkeypatch):
    requested = {}

    def fake_get(url, *, params, timeout):
        requested.update(url=url, params=params, timeout=timeout)
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"featureTypes": [{"properties": [{"name": "road_id", "type": "xsd:int"}]}]},
        )

    monkeypatch.setattr("requests.get", fake_get)
    layer = SimpleNamespace(layer_type="wms", tile_url_template="https://maps.example.test/wms")

    assert GetLayerFieldsUseCase._fetch_remote_fields(layer, {"layerName": "workspace:roads"}) == ["road_id"]
    assert requested["params"]["typeNames"] == "workspace:roads"
