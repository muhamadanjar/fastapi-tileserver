from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from fastapi import HTTPException

from app.presentation.router.api.v1.endpoints.layers import get_layer_legend
from app.core.config import settings
from app.domain.models import Layer
from app.infrastructure.services.legend_renderer import is_stale, raster_fingerprint, vector_fingerprint


class FakeLayerRepository:
    def __init__(self, layer):
        self.layer = layer

    async def get_by_id(self, layer_id):
        return self.layer if self.layer and self.layer.id == layer_id else None


class FakeSessionRepository:
    def __init__(self, session=None):
        self.session = session

    async def get_by_id(self, session_id):
        return self.session


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


async def _execute(layer_id="layer-1", session=None, **layer_overrides):
    return await get_layer_legend(
        layer_id,
        repo=FakeLayerRepository(make_layer(**layer_overrides)),
        session_repo=FakeSessionRepository(session),
    )


# ── WMS ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wms_legend_uses_configured_layer_name():
    result = await _execute()

    assert result.available is True
    assert result.format == "image/png"
    assert result.legend_url == (
        "https://maps.example.test/geoserver/wms?transparent=true&service=WMS&"
        "request=GetLegendGraphic&version=1.3.0&layer=workspace%3Aroads&format=image%2Fpng"
    )


@pytest.mark.asyncio
async def test_wms_legend_falls_back_to_geoserver_layer_name():
    result = await _execute(file_metadata={"geoserver": {"layer_name": "gs:roads"}})

    assert result.available is True
    assert "layer=gs%3Aroads" in result.legend_url


@pytest.mark.asyncio
async def test_wms_legend_unavailable_when_no_layer_name():
    result = await _execute(file_metadata={})

    assert result.available is False
    assert "not configured" in result.detail


# ── Esri ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_esri_mapserver_legend():
    result = await _execute(
        layer_type="esri_mapserver",
        tile_url_template="https://services.example.test/arcgis/rest/services/roads/MapServer/2",
    )

    assert result.available is True
    assert result.format == "application/json"
    assert result.legend_url == "https://services.example.test/arcgis/rest/services/roads/MapServer/legend?f=pjson"


@pytest.mark.asyncio
async def test_esri_imageserver_legend():
    result = await _execute(
        layer_type="esri_imageserver",
        tile_url_template="https://services.example.test/arcgis/rest/services/dem/ImageServer",
    )

    assert result.available is True
    assert result.legend_url == "https://services.example.test/arcgis/rest/services/dem/ImageServer/legend?f=pjson"


@pytest.mark.asyncio
async def test_esri_featureserver_legend():
    result = await _execute(
        layer_type="esri_featureserver",
        tile_url_template="https://services.example.test/arcgis/rest/services/parcels/FeatureServer/0",
    )

    assert result.available is True
    assert result.legend_url == "https://services.example.test/arcgis/rest/services/parcels/FeatureServer/legend?f=pjson"


@pytest.mark.asyncio
async def test_esri_unavailable_when_bad_url():
    result = await _execute(
        layer_type="esri_mapserver",
        tile_url_template="not-a-url",
    )

    assert result.available is False
    assert "does not point to" in result.detail


# ── WMTS ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wmts_legend_with_layer_name():
    result = await _execute(
        layer_type="wmts",
        tile_url_template="https://wmts.example.test/tile/1.0.0/WMTSCapabilities.xml",
        file_metadata={"layer": "topp:states"},
    )

    assert result.available is True
    assert result.format == "image/png"
    assert "layer=topp%3Astates" in result.legend_url


@pytest.mark.asyncio
async def test_wmts_legend_unavailable_without_layer_name():
    result = await _execute(
        layer_type="wmts",
        tile_url_template="https://wmts.example.test/tile/1.0.0/WMTSCapabilities.xml",
        file_metadata={},
    )

    assert result.available is False
    assert "layer name" in result.detail


# ── local vector (mvt / vector / geojson / kml) ──────────────────────

@pytest.mark.asyncio
async def test_local_vector_legend_renders_png(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TILES_DIR", tmp_path / "tiles")
    result = await _execute(
        layer_type="mvt",
        file_type="vector",
        tile_url_template="",
        file_metadata={
            "style": {
                "Point": {"fillColor": "#ff0000", "pointRadius": 5},
                "LineString": {"strokeColor": "#00ff00", "strokeWidth": 2},
                "Polygon": {"fillColor": "#0000ff", "opacity": 0.5},
            }
        },
    )

    assert result.available is True
    assert result.format == "image/png"
    assert result.legend_url == "/tiles/layer-1/legend.png"
    png = tmp_path / "tiles" / "layer-1" / "legend.png"
    assert png.exists()
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_local_vector_legend_normalizes_editor_state(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TILES_DIR", tmp_path / "tiles")
    result = await _execute(
        layer_type="geojson",
        file_type="geojson",
        tile_url_template="",
        file_metadata={
            "style": {
                "mode": "simple",
                "simple": {"Polygon": {"fillColor": "#123456"}},
            }
        },
    )

    assert result.available is True
    assert (tmp_path / "tiles" / "layer-1" / "legend.png").exists()


@pytest.mark.asyncio
async def test_local_vector_legend_without_style_uses_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TILES_DIR", tmp_path / "tiles")
    result = await _execute(
        layer_type="kml",
        file_type="vector",
        tile_url_template="",
        file_metadata={},
    )

    assert result.available is True
    assert "default style" in result.detail
    assert (tmp_path / "tiles" / "layer-1" / "legend.png").exists()


# ── local raster (tile) ──────────────────────────────────────────────

def _make_tiff(path):
    with rasterio.open(
        path, "w", driver="GTiff", height=2, width=2, count=1, dtype="uint8"
    ) as dst:
        dst.write(np.array([[0, 128], [200, 255]], dtype="uint8"), 1)


@pytest.mark.asyncio
async def test_local_raster_legend_renders_from_source(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TILES_DIR", tmp_path / "tiles")
    src = tmp_path / "src.tif"
    _make_tiff(src)
    session = SimpleNamespace(id="s1", filename="src.tif", final_path=str(src))

    result = await _execute(
        layer_type="tile", file_type="raster", tile_url_template="",
        upload_session_id="s1", session=session,
    )

    assert result.available is True
    assert result.legend_url == "/tiles/layer-1/legend.png"
    assert (tmp_path / "tiles" / "layer-1" / "legend.png").exists()


@pytest.mark.asyncio
async def test_local_raster_legend_unavailable_without_source():
    result = await _execute(layer_type="tile", file_type="raster", tile_url_template="", session=None)

    assert result.available is False
    assert "Source file not found" in result.detail


# ── unsupported types ────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("layer_type", ["wfs", "postgis", "esri_vectortileserver"])
async def test_unsupported_types_return_unavailable(layer_type):
    result = await _execute(layer_type=layer_type)

    assert result.available is False
    assert result.legend_url is None


# ── fingerprint / cache ──────────────────────────────────────────────

def test_vector_fingerprint_changes_with_style():
    a = vector_fingerprint({"Polygon": {"fillColor": "#111111"}})
    b = vector_fingerprint({"Polygon": {"fillColor": "#222222"}})
    assert a != b


def test_is_stale_true_when_fingerprint_differs(tmp_path):
    png = tmp_path / "legend.png"
    png.write_bytes(b"x")
    (tmp_path / "legend.png.fp").write_text("old")
    assert is_stale(png, "new") is True


# ── missing layer ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_layer_returns_404():
    with pytest.raises(HTTPException, match="not found") as exc_info:
        await get_layer_legend("missing", repo=FakeLayerRepository(None), session_repo=FakeSessionRepository())

    assert exc_info.value.status_code == 404
