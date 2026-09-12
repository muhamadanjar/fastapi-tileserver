from datetime import datetime

import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon, box

from app.analysis.intersection_area import AREA_FIELDS, intersect_with_area, prepare_area_input


def frame(geometries, **attributes):
    return gpd.GeoDataFrame(attributes, geometry=geometries, crs="EPSG:6933")


def measure(a, b, **kwargs):
    return intersect_with_area(
        prepare_area_input(a, "a", kwargs.get("id_a"), "run"),
        prepare_area_input(b, "b", kwargs.get("id_b"), "run"),
        kwargs.get("selected"),
    )


def test_agreed_area_percentages_and_attribute_collisions():
    a = frame([box(0, 0, 1000, 1000)], code=["A"], area_m2=[999], name=["left"])
    b = frame([box(800, 0, 1200, 1000)], code=["B"], area_m2=[888], name=["right"])
    original = a.copy()
    result = measure(a, b, id_a="code", id_b="code",
                     selected={"layer_a": ["area_m2"], "layer_b": ["name"]})
    row = result.iloc[0]
    assert row.src_a_id == "A" and row.src_b_id == "B"
    assert row.src_a_row == row.src_b_row == 0
    assert row.area_m2 == pytest.approx(200_000)
    assert row.area_ha == pytest.approx(20)
    assert row.pct_a == pytest.approx(20)
    assert row.pct_b == pytest.approx(50)
    assert row.a_area_m2 == 999 and row.b_name == "right"
    assert "a_name" not in result and "b_area_m2" not in result
    assert result.crs.to_epsg() == 4326
    assert a.equals(original)


def test_overlapping_pairs_are_independent_not_unique_coverage():
    result = measure(
        frame([box(0, 0, 1000, 1000)]),
        frame([box(0, 0, 800, 1000), box(200, 0, 1000, 1000)]),
    )
    assert len(result) == 2
    assert result.area_m2.sum() == pytest.approx(1_600_000)
    assert result.pct_a.tolist() == pytest.approx([80, 80])
    assert result.src_b_row.tolist() == [0, 1]


@pytest.mark.parametrize("other", [box(10, 0, 20, 10), box(10, 10, 20, 20), box(20, 20, 30, 30)])
def test_boundary_only_and_disjoint_pairs_are_empty(other):
    result = measure(frame([box(0, 0, 10, 10)]), frame([other]))
    assert result.empty
    assert set(AREA_FIELDS) <= set(result.columns)


@pytest.mark.parametrize("empty_side", ["a", "b", "both"])
def test_empty_layers_have_typed_empty_results(empty_side):
    a = frame([] if empty_side in ("a", "both") else [box(0, 0, 10, 10)])
    b = frame([] if empty_side in ("b", "both") else [box(0, 0, 10, 10)])
    result = measure(a, b)
    assert result.empty
    assert set(AREA_FIELDS) <= set(result.columns)


def test_holes_and_multipart_keep_one_pair_and_full_denominators():
    donut = Polygon(box(0, 0, 10, 10).exterior.coords, [box(2, 2, 8, 8).exterior.coords])
    a = frame([MultiPolygon([donut, box(20, 0, 30, 10)])])
    b = frame([box(-1, -1, 31, 11)])
    result = measure(a, b)
    assert len(result) == 1
    assert result.iloc[0].area_m2 == pytest.approx(164)
    assert result.iloc[0].pct_a == pytest.approx(100)
    assert result.iloc[0].pct_b == pytest.approx(100 * 164 / 384)
    assert result.iloc[0].geometry.geom_type == "MultiPolygon"


def test_small_positive_overlap_is_not_rounded_away():
    result = measure(frame([box(0, 0, 1, 1)]), frame([box(0, 0, .001, .001)]))
    assert len(result) == 1
    assert result.iloc[0].area_m2 == pytest.approx(.000001)
    assert result.iloc[0].area_ha > 0


def test_different_crs_have_consistent_measurements():
    a = frame([box(10_000_000, -1_000_000, 10_001_000, -999_000)])
    b = frame([box(10_000_800, -1_000_000, 10_001_200, -999_000)])
    expected = measure(a, b)
    actual = measure(a.to_crs(4326), b.to_crs(3857))
    assert actual.iloc[0].area_m2 == pytest.approx(expected.iloc[0].area_m2, rel=1e-6)
    assert actual.iloc[0].pct_a == pytest.approx(20, rel=1e-6)
    assert actual.iloc[0].pct_b == pytest.approx(50, rel=1e-6)


@pytest.mark.parametrize("geometry, reason", [
    (None, "null or empty"), (Polygon(), "null or empty"),
    (Point(0, 0), "requires Polygon"),
    (Polygon([(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)]), "Self-intersection"),
    (Polygon([(0, 0), (1, 1), (2, 2), (0, 0)]), "Self-intersection"),
])
def test_invalid_geometry_reports_source_id_without_repair(geometry, reason):
    with pytest.raises(ValueError, match=reason) as error:
        prepare_area_input(frame([geometry], code=["bad-feature"]), "a", "code", "run")
    assert "bad-feature" in str(error.value)
    assert "Layer A" in str(error.value)


@pytest.mark.parametrize("ids", [["x", "x"], ["x", None], ["x", "  "], ["x", float("inf")], ["x", True]])
def test_invalid_ids_are_rejected(ids):
    with pytest.raises(ValueError, match="ID"):
        prepare_area_input(frame([box(0, 0, 1, 1)] * 2, code=ids), "a", "code", "run")


def test_missing_id_field_and_selected_attribute_are_rejected():
    a = frame([box(0, 0, 1, 1)])
    with pytest.raises(ValueError, match="not an attribute"):
        prepare_area_input(a, "a", "missing", "run")
    with pytest.raises(ValueError, match="unknown selected attributes"):
        prepare_area_input(a, "a", None, "run", {"layer_a": ["missing"]})


def test_generated_ids_map_to_snapshot_despite_duplicate_dataframe_index():
    a = frame([box(0, 0, 1, 1), box(2, 2, 3, 3)], name=["first", "second"])
    a.index = [9, 9]
    prepared = prepare_area_input(a, "a", None, "run-unique")
    snapshot = prepared.snapshot("layer-A")
    assert prepared.ids == ["run-unique:a:0", "run-unique:a:1"]
    assert [f["id"] for f in snapshot["features"]] == prepared.ids
    assert snapshot["features"][1]["properties"]["name"] == "second"
    assert snapshot["features"][1]["source_row"] == 1
    assert snapshot["layer_id"] == "layer-A"


def test_snapshot_preserves_date_attributes_as_strings():
    prepared = prepare_area_input(
        frame([box(0, 0, 1, 1)], observed=[datetime(2026, 9, 12)]), "a", None, "run",
    )
    assert prepared.snapshot("a")["features"][0]["properties"]["observed"].startswith("2026-09-12")


def test_missing_crs_and_unsupported_projection_domain_rejected():
    with pytest.raises(ValueError, match="CRS is required"):
        prepare_area_input(gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)]), "a", None, "run")
    for geometry in [box(-179, 0, 179, 1), box(0, 87, 1, 88)]:
        with pytest.raises(ValueError, match="outside area measurement domain"):
            prepare_area_input(gpd.GeoDataFrame(geometry=[geometry], crs=4326), "a", None, "run")
