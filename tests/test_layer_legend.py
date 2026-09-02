from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.layers import get_layer_legend
from app.domain.models import Layer


class FakeLayerRepository:
    def __init__(self, layer):
        self.layer = layer

    async def get_by_id(self, layer_id):
        return self.layer if self.layer and self.layer.id == layer_id else None


def make_layer(**overrides):
    values = {
        "id": "layer-1",
        "filename": "roads",
        "file_type": "external",
        "tile_url_template": "https://maps.example.test/geoserver/wms?transparent=true",
        "layer_type": "wms",
        "created_at": datetime.now(timezone.utc),
        "file_metadata": {"layers": "workspace:roads"},
    }
    values.update(overrides)
    return Layer(**values)


@pytest.mark.asyncio
async def test_wms_legend_uses_configured_layer_name():
    result = await get_layer_legend("layer-1", repo=FakeLayerRepository(make_layer()))

    assert result.available is True
    assert result.format == "image/png"
    assert result.legend_url == (
        "https://maps.example.test/geoserver/wms?transparent=true&service=WMS&"
        "request=GetLegendGraphic&version=1.3.0&layer=workspace%3Aroads&format=image%2Fpng"
    )


@pytest.mark.asyncio
async def test_esri_legend_uses_service_native_endpoint():
    layer = make_layer(
        layer_type="esri_mapserver",
        tile_url_template="https://services.example.test/arcgis/rest/services/roads/MapServer/2",
    )

    result = await get_layer_legend("layer-1", repo=FakeLayerRepository(layer))

    assert result.available is True
    assert result.format == "application/json"
    assert result.legend_url == "https://services.example.test/arcgis/rest/services/roads/MapServer/legend?f=pjson"


@pytest.mark.asyncio
async def test_non_service_layer_reports_no_legend():
    result = await get_layer_legend(
        "layer-1", repo=FakeLayerRepository(make_layer(layer_type="mvt"))
    )

    assert result.available is False
    assert result.legend_url is None


@pytest.mark.asyncio
async def test_missing_layer_returns_404():
    with pytest.raises(HTTPException, match="not found") as exc_info:
        await get_layer_legend("missing", repo=FakeLayerRepository(None))

    assert exc_info.value.status_code == 404
