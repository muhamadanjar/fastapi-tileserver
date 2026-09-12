"""Tests for MVT group composite publishing and legend_for_group."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
import zipfile

import pytest

from app.domain.map_batches import Batch, Dataset, Group, LayerData, Member
from app.infrastructure.services.map_renderer import (
    FileBackedMapRenderer,
    _detect_datasets_from_zip,
    _group_styles_dir,
    _style_for_tiler,
)
from PIL import Image


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_layer(
    layer_id: str = "layer-1",
    *,
    style: dict | None = None,
    output_format: str = "mvt",
    name: str = "Test Layer",
) -> LayerData:
    return LayerData(
        id=layer_id,
        code=layer_id,
        name=name,
        output_format=output_format,
        upload_id="up-1",
        bbox=[0, 0, 10, 10],
        style=style or {
            "Polygon": {"fillColor": "#aabbcc", "strokeColor": "#112233", "strokeWidth": 1, "opacity": 0.6},
            "LineString": {"strokeColor": "#ff0000", "strokeWidth": 3, "opacity": 0.9},
        },
        metadata={},
        url=f"/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.pbf",
    )


def _make_group(
    members: list[Member] | None = None,
    output_format: str = "mvt",
) -> Group:
    return Group(
        id="grp-1",
        code="test-grp",
        name="Test Group",
        output_format=output_format,
        members=members or [Member(layer_id="layer-1", visible=True)],
        status="published",
    )


# ---------------------------------------------------------------------------
# _style_for_tiler
# ---------------------------------------------------------------------------

class TestStyleForTilerGuard:
    def test_returns_same_reference_when_already_rgb(self):
        style = {"Polygon": {"fillColor": [51, 136, 255], "strokeColor": [0, 0, 0]}}
        result = _style_for_tiler(style)
        assert result is style  # same object, no conversion

    def test_converts_hex_to_rgb(self):
        style = {"Polygon": {"fillColor": "#3388ff", "strokeColor": "#000000"}}
        result = _style_for_tiler(style)
        assert result["Polygon"]["fillColor"] == [51, 136, 255]
        assert result["Polygon"]["strokeColor"] == [0, 0, 0]

    def test_empty_style(self):
        assert _style_for_tiler({}) == {}
        assert _style_for_tiler(None) == {}  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# MVT group composite
# ---------------------------------------------------------------------------

class TestPublishMVTGroup:
    def test_creates_style_json(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(
            "app.infrastructure.services.map_renderer.settings",
            type("S", (), {"TILES_DIR": tmp_path, "UPLOAD_DIR": tmp_path})(),
        )
        renderer = FileBackedMapRenderer()
        layer = _make_layer()
        group = _make_group()

        renderer.publish(group, [layer])

        style_file = _group_styles_dir() / "test-grp" / "style.json"
        assert style_file.exists()

        data = json.loads(style_file.read_text())
        assert data["version"] == 8
        assert data["sources"]["group"]["tiles"] == ["/tiles/_group/test-grp/{z}/{x}/{y}.pbf"]
        ids = {e["id"] for e in data["layers"]}
        assert "layer-1_Polygon" in ids
        assert "layer-1_LineString" in ids

    def test_invisible_member_set_to_none(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(
            "app.infrastructure.services.map_renderer.settings",
            type("S", (), {"TILES_DIR": tmp_path, "UPLOAD_DIR": tmp_path})(),
        )
        renderer = FileBackedMapRenderer()
        layer = _make_layer()
        group = _make_group(members=[Member(layer_id="layer-1", visible=False)])

        renderer.publish(group, [layer])

        style_file = _group_styles_dir() / "test-grp" / "style.json"
        data = json.loads(style_file.read_text())
        for entry in data["layers"]:
            assert entry["layout"]["visibility"] == "none"

    def test_wms_group_skips_mvt_path(self, tmp_path: Path, monkeypatch):
        """WMS groups must NOT write a style.json — that's GeoServer's job."""
        monkeypatch.setattr(
            "app.infrastructure.services.map_renderer.settings",
            type("S", (), {"TILES_DIR": tmp_path, "UPLOAD_DIR": tmp_path})(),
        )
        renderer = FileBackedMapRenderer()
        group = _make_group(output_format="wms")
        # Will call self._get_gs() which raises without env — acceptable for this check
        try:
            renderer.publish(group, [_make_layer(output_format="wms")])
        except Exception:
            pass
        assert not (_group_styles_dir() / "test-grp").exists()


# ---------------------------------------------------------------------------
# legend_for_group
# ---------------------------------------------------------------------------

class TestLegendForGroup:
    def test_returns_symbols_for_each_geom(self):
        renderer = FileBackedMapRenderer()
        layer = _make_layer()
        group = _make_group()

        legend = renderer.legend_for_group(group, [layer])
        assert len(legend) == 1

        entry = legend[0]
        assert entry["layer_id"] == "layer-1"
        assert entry["visible"] is True
        assert entry["sort_order"] == 0

        geom_types = {s["geometry"] for s in entry["symbols"]}
        assert "Polygon" in geom_types
        assert "LineString" in geom_types

    def test_invisible_member_is_excluded(self):
        renderer = FileBackedMapRenderer()
        group = _make_group(members=[Member(layer_id="layer-1", visible=False)])

        legend = renderer.legend_for_group(group, [_make_layer()])
        assert legend == []

    def test_empty_layers(self):
        renderer = FileBackedMapRenderer()
        group = _make_group()
        assert renderer.legend_for_group(group, []) == []

    def test_point_symbol_includes_point_radius(self):
        renderer = FileBackedMapRenderer()
        layer = _make_layer(style={"Point": {"fillColor": "#ee0000", "strokeColor": "#333", "pointRadius": 8}})
        group = _make_group(members=[Member(layer_id="layer-1", visible=True)])

        legend = renderer.legend_for_group(group, [layer])
        point_sym = [s for s in legend[0]["symbols"] if s["geometry"] == "Point"][0]
        assert point_sym["pointRadius"] == 8


# ---------------------------------------------------------------------------
# remove (MVT cleanup)
# ---------------------------------------------------------------------------

class TestRemoveMVTGroup:
    def test_removes_group_style_dir(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(
            "app.infrastructure.services.map_renderer.settings",
            type("S", (), {"TILES_DIR": tmp_path, "UPLOAD_DIR": tmp_path})(),
        )
        renderer = FileBackedMapRenderer()
        group = _make_group()
        renderer.publish(group, [_make_layer()])
        style_dir = _group_styles_dir() / "test-grp"
        assert style_dir.exists()

        renderer.remove(group)
        assert not style_dir.exists()


class TestCompositeTiles:
    def test_composes_visible_raster_members_in_order(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(
            "app.infrastructure.services.map_renderer.settings",
            type("S", (), {"TILES_DIR": tmp_path, "UPLOAD_DIR": tmp_path})(),
        )
        for layer_id, color in (("bottom", (255, 0, 0, 255)), ("top", (0, 0, 255, 128))):
            path = tmp_path / layer_id / "0" / "0"
            path.mkdir(parents=True)
            Image.new("RGBA", (2, 2), color).save(path / "0.png")
        group = _make_group(members=[Member("bottom"), Member("top")], output_format="raster")
        layers = [_make_layer("bottom", output_format="raster"), _make_layer("top", output_format="raster")]

        tile = FileBackedMapRenderer().compose_raster_tile(group, layers, 0, 0, 0)

        assert tile is not None
        assert Image.open(__import__("io").BytesIO(tile)).convert("RGBA").getpixel((0, 0)) == (127, 0, 128, 255)

    def test_merges_mvt_member_layers(self, tmp_path: Path, monkeypatch):
        import mapbox_vector_tile

        monkeypatch.setattr(
            "app.infrastructure.services.map_renderer.settings",
            type("S", (), {"TILES_DIR": tmp_path, "UPLOAD_DIR": tmp_path})(),
        )
        for layer_id in ("first", "second"):
            path = tmp_path / layer_id / "0" / "0"
            path.mkdir(parents=True)
            path.joinpath("0.pbf").write_bytes(mapbox_vector_tile.encode({
                "name": layer_id,
                "features": [{"geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": {"id": layer_id}}],
            }, default_options={"extents": 4096, "y_coord_down": True}))
        group = _make_group(members=[Member("first"), Member("second")])
        layers = [_make_layer("first"), _make_layer("second")]

        tile = FileBackedMapRenderer().compose_mvt_tile(group, layers, 0, 0, 0)

        assert tile is not None
        assert set(mapbox_vector_tile.decode(tile)) == {"first", "second"}


class TestArchiveSafety:
    def test_rejects_path_traversal_before_extracting(self, tmp_path: Path):
        archive = tmp_path / "unsafe.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../roads.shp", b"not a shapefile")

        with pytest.raises(Exception, match="Unsafe ZIP entry"):
            _detect_datasets_from_zip(archive)

    def test_rejects_duplicate_member_names(self, tmp_path: Path):
        archive = tmp_path / "duplicate.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("roads.shp", b"first")
            zf.writestr("ROADS.SHP", b"second")

        with pytest.raises(Exception, match="duplicate file names"):
            _detect_datasets_from_zip(archive)
