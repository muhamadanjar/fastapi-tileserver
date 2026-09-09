"""Runnable self-check for overlay analysis core operations.

Run: venv/bin/python -m tests.test_overlay_operations
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon

from app.analysis.geometry_compat import get_compatible_operations, is_compatible
from app.analysis.overlay_operations import (
    _convert_to_meters,
    buffer,
    centroid,
    clip,
    difference,
    dissolve,
    intersection,
    simplify,
    spatial_join,
    sym_difference,
    union,
)
import pandas as pd

SQUARE = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
INNER = Polygon([(3, 3), (7, 3), (7, 7), (3, 7)])


def make(gdf_list, **kw):
    return gpd.GeoDataFrame(gdf_list, crs="EPSG:4326", **kw)


def test_intersection_point_in_polygon():
    pts = make([{"geometry": Point(5, 5), "name": "in"}, {"geometry": Point(50, 50), "name": "out"}])
    poly = make([{"geometry": SQUARE}])
    r = intersection(poly, pts)
    assert len(r) == 1, f"expected 1, got {len(r)}"
    assert r.iloc[0]["name"] == "in"


def test_intersection_line_clip():
    lines = make([{"geometry": LineString([(0, 0), (10, 10)])}])
    poly = make([{"geometry": Polygon([(-1, -1), (6, -1), (6, 6), (-1, 6)])}])
    r = intersection(poly, lines)
    assert len(r) == 1
    assert abs(r.iloc[0].geometry.length - 8.48528137423857) < 1e-9  # sqrt(72)


def test_intersection_polygon():
    a = make([{"geometry": SQUARE}])
    b = make([{"geometry": Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])}])
    r = intersection(a, b)
    assert len(r) == 1
    assert r.iloc[0].geometry.area == 25.0


def test_union_area():
    a = make([{"geometry": SQUARE}])
    b = make([{"geometry": Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])}])
    r = union(a, b)
    assert r.area.sum() == 175.0  # 100 + 100 - 25


def test_clip_points():
    pts = make([{"geometry": Point(5, 5), "name": "in"}, {"geometry": Point(50, 50), "name": "out"}])
    poly = make([{"geometry": SQUARE}])
    r = clip(pts, poly)
    assert len(r) == 1
    assert r.iloc[0]["name"] == "in"


def test_difference_area():
    a = make([{"geometry": SQUARE}])
    b = make([{"geometry": INNER}])
    r = difference(a, b)
    assert len(r) == 1
    assert r.iloc[0].geometry.area == 84.0  # 100 - 16


def test_dissolve_group_and_full():
    g = make(
        [
            {"geometry": Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]), "grp": "x"},
            {"geometry": Polygon([(2, 0), (4, 0), (4, 2), (2, 2)]), "grp": "x"},
            {"geometry": Polygon([(10, 10), (12, 10), (12, 12), (10, 12)]), "grp": "y"},
        ]
    )
    by_group = dissolve(g, "grp")
    assert len(by_group) == 2
    full = dissolve(g, None)
    assert len(full) == 1


def test_buffer_units_and_geographic():
    g = make([{"geometry": Point(0, 0)}])
    r = buffer(g, 1, "kilometers")
    assert len(r) == 1
    assert r.iloc[0].geometry.geom_type == "Polygon"


def test_convert_to_meters():
    assert _convert_to_meters(1, "kilometers") == 1000.0
    assert _convert_to_meters(1, "feet") == 0.3048
    assert _convert_to_meters(1, "miles") == 1609.344
    assert _convert_to_meters(1, "meters") == 1.0


def test_compatibility():
    assert is_compatible("intersection", "polygon", "point")
    assert is_compatible("clip", "point", "polygon")
    assert not is_compatible("union", "polygon", "point")
    assert not is_compatible("difference", "line", "polygon")
    ops = get_compatible_operations("polygon", "polygon")
    assert "intersection" in ops and "union" in ops and "difference" in ops


def test_sym_difference_area():
    a = make([{"geometry": SQUARE}])
    b = make([{"geometry": Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])}])
    r = sym_difference(a, b)
    assert r.area.sum() == 150.0  # 100 + 100 - 2*25


def test_simplify_reduces_vertices():
    jagged = Polygon([(0, 0), (1, 0.1), (2, -0.1), (3, 0.05), (4, 0), (4, 4), (0, 4)])
    g = make([{"geometry": jagged}])
    before = len(g.iloc[0].geometry.exterior.coords)
    r = simplify(g, 0.5)
    after = len(r.iloc[0].geometry.exterior.coords)
    assert after < before, f"expected fewer vertices, got {before}->{after}"


def test_spatial_join_attrs():
    polys = make([{"geometry": SQUARE, "zone": "core"}])
    pts = make([{"geometry": Point(5, 5), "name": "inside"}, {"geometry": Point(50, 50), "name": "outside"}])
    r = spatial_join(pts, polys, "within")
    inside = r[r["name"] == "inside"]
    assert not inside.empty and inside.iloc[0]["zone"] == "core"
    outside = r[r["name"] == "outside"]
    assert outside.empty or pd.isna(outside.iloc[0].get("zone"))


def test_centroid_points():
    g = make([{"geometry": Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])}])
    r = centroid(g)
    assert r.iloc[0].geometry.geom_type == "Point"
    assert r.iloc[0].geometry.x == 5.0 and r.iloc[0].geometry.y == 5.0


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"\n{len(tests)} tests passed")


if __name__ == "__main__":
    main()