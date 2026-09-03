from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.v1.endpoints import layers as layer_endpoints
from app.domain.schemas import ExternalLayerRequest, PatchLayerRequest, SyncBBoxRequest


class FakeLayerRepository:
    def __init__(self, layer):
        self.layer = layer
        self.update_kwargs = None

    async def get_by_id(self, layer_id):
        return self.layer if layer_id == self.layer.id else None

    async def update(self, layer_id, **kwargs):
        if layer_id != self.layer.id:
            return None
        self.update_kwargs = kwargs
        for name, value in kwargs.items():
            if value is not None:
                setattr(self.layer, name, value)
        return self.layer

    async def code_exists(self, _code):
        return False

    async def create(self, layer):
        self.layer = layer
        return layer


class UnusedUploadRepository:
    async def get_by_id(self, _upload_id):
        raise AssertionError("manual bbox sync must not access an upload session")


def make_layer(**overrides):
    values = {
        "id": "layer-1",
        "upload_session_id": None,
        "code": "manual-layer",
        "layer_type": "wms",
        "filename": "Manual layer",
        "file_type": "external",
        "tile_url_template": "https://example.com/wms",
        "created_at": datetime.now(timezone.utc),
        "bbox_west": None,
        "bbox_south": None,
        "bbox_east": None,
        "bbox_north": None,
        "file_metadata": {},
        "abstract": None,
        "topic_category": None,
        "language": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_sync_bbox_uses_manual_values_and_syncs_catalog(monkeypatch):
    layer = make_layer()
    repo = FakeLayerRepository(layer)
    synced_layers = []

    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(layer_endpoints, "sync_layer", synced_layers.append)
    monkeypatch.setattr(layer_endpoints.asyncio, "to_thread", run_inline)

    response = await layer_endpoints.sync_layer_bbox(
        "layer-1",
        repo=repo,
        upload_repo=UnusedUploadRepository(),
        req=SyncBBoxRequest(bbox=[0, -10, 20, 10]),
    )

    assert response["bbox"] == [0.0, -10.0, 20.0, 10.0]
    assert repo.update_kwargs["bbox_west"] == 0.0
    assert repo.update_kwargs["bbox_south"] == -10.0
    assert repo.update_kwargs["bbox_east"] == 20.0
    assert repo.update_kwargs["bbox_north"] == 10.0
    assert synced_layers == [layer]


@pytest.mark.asyncio
async def test_layer_response_keeps_valid_zero_coordinate():
    layer = make_layer(
        bbox_west=0.0,
        bbox_south=-10.0,
        bbox_east=20.0,
        bbox_north=10.0,
    )

    response = await layer_endpoints.get_layer(
        "layer-1",
        repo=FakeLayerRepository(layer),
        session_repo=UnusedUploadRepository(),
    )

    assert response.bbox == [0.0, -10.0, 20.0, 10.0]


@pytest.mark.parametrize(
    "bbox",
    (
        [100, -10, 100, 10],
        [-181, -10, 100, 10],
        [100, -91, 110, 10],
        [100, -10, float("nan"), 10],
        [100, -10, 110],
    ),
)
def test_manual_bbox_validation_rejects_invalid_extents(bbox):
    with pytest.raises(ValidationError):
        SyncBBoxRequest(bbox=bbox)

    with pytest.raises(ValidationError):
        ExternalLayerRequest(
            layer_type="wms",
            filename="Invalid bbox",
            source_url="https://example.com/wms",
            bbox=bbox,
        )


@pytest.mark.asyncio
async def test_external_layer_accepts_manual_file_metadata_shape(monkeypatch):
    repo = FakeLayerRepository(make_layer())
    synced_layers = []

    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(layer_endpoints, "sync_layer", synced_layers.append)
    monkeypatch.setattr(layer_endpoints.asyncio, "to_thread", run_inline)

    response = await layer_endpoints.add_external_layer(
        ExternalLayerRequest(
            layer_type="wms",
            filename="Manual GeoServer WMS",
            source_url="https://geo.example.com/geoserver/workspace/wms",
            file_metadata={"layers": "workspace:roads", "format": "image/png"},
            bbox=[106, -7, 108, -5],
        ),
        repo=repo,
    )

    assert repo.layer.file_metadata["layers"] == "workspace:roads"
    assert repo.layer.file_metadata["format"] == "image/png"
    assert response.bbox == [106.0, -7.0, 108.0, -5.0]
    assert synced_layers == [repo.layer]


@pytest.mark.asyncio
async def test_patch_layer_accepts_source_url_from_manual_form(monkeypatch):
    layer = make_layer(
        bbox_west=106.0,
        bbox_south=-7.0,
        bbox_east=108.0,
        bbox_north=-5.0,
    )
    repo = FakeLayerRepository(layer)
    synced_layers = []

    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(layer_endpoints, "sync_layer", synced_layers.append)
    monkeypatch.setattr(layer_endpoints.asyncio, "to_thread", run_inline)

    response = await layer_endpoints.patch_layer(
        "layer-1",
        PatchLayerRequest(
            source_url="https://geo.example.com/geoserver/workspace/wms",
            file_metadata={"layers": "workspace:roads"},
        ),
        repo=repo,
        session_repo=UnusedUploadRepository(),
    )

    assert repo.layer.tile_url_template == "https://geo.example.com/geoserver/workspace/wms"
    assert repo.layer.file_metadata["layers"] == "workspace:roads"
    assert response.tile_url_template == repo.layer.tile_url_template
    assert synced_layers == [repo.layer]
