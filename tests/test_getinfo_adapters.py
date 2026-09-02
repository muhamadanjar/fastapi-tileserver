from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from app.usecases.getinfo_adapters import (
    ClientSideAdapter,
    EsriFeatureServerAdapter,
    EsriMapserverAdapter,
    VectorSourceAdapter,
    WmsAdapter,
    resolve_adapter,
)
from app.usecases import getinfo_layer
from app.usecases.getinfo_layer import QueryLayerFeaturesUseCase


def _layer(file_type, layer_type):
    return SimpleNamespace(
        file_type=file_type,
        layer_type=layer_type,
        tile_url_template="",
        file_metadata=None,
        upload_session_id=None,
    )


class _StubRepo:
    def __init__(self, layer):
        self._layer = layer

    async def get_by_id(self, layer_id):
        return self._layer


def test_local_mvt_layer_uses_its_authoritative_vector_source():
    layer = _layer("vector", "mvt")
    assert isinstance(resolve_adapter(layer), VectorSourceAdapter)


def test_routing_resolves_expected_adapter_types():
    assert isinstance(resolve_adapter(_layer("external", "wms")), WmsAdapter)
    assert isinstance(resolve_adapter(_layer("external", "esri_mapserver")), EsriMapserverAdapter)
    assert isinstance(resolve_adapter(_layer("external", "esri_featureserver")), EsriFeatureServerAdapter)
    assert isinstance(resolve_adapter(_layer("vector", "mvt")), VectorSourceAdapter)
    # unhandled external type -> empty fallback (no hint)
    layer = _layer("external", "unknown")
    assert resolve_adapter(layer).query(layer, 1, 2, None).response.query_hint is None


def test_external_vector_tile_layer_keeps_client_hint():
    layer = _layer("external", "esri_vectortileserver")
    result = resolve_adapter(layer).query(layer, 106.8, -6.2, None)
    assert result.query_hint == "client"


@pytest.mark.asyncio
async def test_raster_tile_without_source_returns_empty_raster():
    layer = _layer("raster", "tile")
    usecase = QueryLayerFeaturesUseCase(_StubRepo(layer), _StubRepo(None))
    response = await usecase.execute("layer-raster", 106.8, -6.2)
    assert response.type == "raster"
    assert response.count == 0
    # no source -> no client hint, empty raster (not a coroutine crash)
    assert response.query_hint is None


@pytest.mark.asyncio
async def test_get_info_renews_artifact_access_with_editor_authorization(tmp_path, monkeypatch):
    layer = _layer("raster", "tile")
    layer.id = "layer-raster"
    layer.upload_session_id = "session-1"
    session = SimpleNamespace(
        id="session-1",
        filename="source.tif",
        final_path="artifact://artifact-1",
    )
    calls = []
    materialized_source = tmp_path / "materialized-source.tif"
    materialized_source.write_bytes(b"raster-source")

    class _ArtifactClient:
        def materialize(self, artifact_id, filename):
            calls.append(("materialize", artifact_id, filename))
            if len([call for call in calls if call[0] == "materialize"]) == 1:
                raise RuntimeError("processing lease has expired")
            return nullcontext(materialized_source)

        def create_user_grant(self, artifact_id, authorization):
            calls.append(("grant", artifact_id, authorization))
            return "grant-1"

        def acquire_lease(self, artifact_id, grant_id, reference):
            calls.append(("lease", artifact_id, grant_id, reference))
            return {"lease_id": "lease-1"}

        def release_lease(self, artifact_id, lease_id):
            calls.append(("release", artifact_id, lease_id))

    monkeypatch.setenv("ARTIFACT_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(getinfo_layer, "UploadArtifactClient", _ArtifactClient)
    usecase = QueryLayerFeaturesUseCase(_StubRepo(layer), _StubRepo(session))

    async with usecase._source_context(layer, authorization="Bearer editor-token") as source_path:
        assert source_path.read_bytes() == b"raster-source"

    assert ("grant", "artifact-1", "Bearer editor-token") in calls
    assert any(call[0] == "lease" and call[1:3] == ("artifact-1", "grant-1") for call in calls)
    assert ("release", "artifact-1", "lease-1") in calls
