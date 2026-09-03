from types import SimpleNamespace

import pytest

from app.usecases import get_features_in_bbox
from app.usecases.get_features_in_bbox import GetFeaturesInBboxUseCase


class FakeLayerRepository:
    def __init__(self, layer):
        self.layer = layer

    async def get_by_id(self, layer_id):
        return self.layer if layer_id == self.layer.id else None


class FakeSessionRepository:
    async def get_by_id(self, _session_id):
        return None


def make_layer(**overrides):
    values = {
        "id": "layer-1",
        "layer_type": "wms",
        "file_type": "external",
        "upload_session_id": None,
        "tile_url_template": "https://geo.example.test/service",
        "file_metadata": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_raster_bbox_query_returns_explicit_unavailable_capability():
    layer = make_layer(layer_type="tile", file_type="raster")

    response = await GetFeaturesInBboxUseCase(
        FakeLayerRepository(layer), FakeSessionRepository()
    ).execute("layer-1", 106, -7, 107, -6)

    assert response.queryable is False
    assert response.count == 0
    assert "Raster" in response.reason


@pytest.mark.asyncio
async def test_wfs_bbox_query_filters_visible_properties(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "features": [
                    {"properties": {"name": "Road A", "hidden": "secret"}},
                    {"properties": {"name": "Road B", "hidden": "secret"}},
                ]
            }

    captured = {}

    def fake_get(url, params, timeout):
        captured.update({"url": url, "params": params, "timeout": timeout})
        return Response()

    monkeypatch.setattr(get_features_in_bbox.requests, "get", fake_get)
    layer = make_layer(
        layer_type="wfs",
        tile_url_template="https://geo.example.test/wfs?typeName=roads",
        file_metadata={"fields": [{"original": "name", "visible": True}]},
    )

    response = await GetFeaturesInBboxUseCase(
        FakeLayerRepository(layer), FakeSessionRepository()
    ).execute("layer-1", 106, -7, 107, -6, limit=1)

    assert response.queryable is True
    assert response.features == [{"name": "Road A"}]
    assert response.exceeded is True
    assert captured["params"]["bbox"] == "106,-7,107,-6,EPSG:4326"


@pytest.mark.asyncio
async def test_esri_bbox_query_uses_sublayer_query_endpoint(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"features": [{"attributes": {"id": 7}}]}

    captured = {}

    def fake_get(url, params, timeout):
        captured.update({"url": url, "params": params})
        return Response()

    monkeypatch.setattr(get_features_in_bbox.requests, "get", fake_get)
    layer = make_layer(
        layer_type="esri_featureserver",
        tile_url_template="https://geo.example.test/FeatureServer/0",
    )

    response = await GetFeaturesInBboxUseCase(
        FakeLayerRepository(layer), FakeSessionRepository()
    ).execute("layer-1", 106, -7, 107, -6)

    assert response.features == [{"id": 7}]
    assert captured["url"].endswith("FeatureServer/0/query")
