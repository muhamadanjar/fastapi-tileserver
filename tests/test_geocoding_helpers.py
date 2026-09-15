"""Self-check for the pure geocoding helpers (no network, no DB)."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.usecases.geocoding import (
    _haversine,
    _radius_bbox,
    _representative_point,
)


def test_haversine_known_distance():
    # One degree of latitude along the meridian ≈ 111.195 km
    dist = _haversine(0.0, 0.0, 0.0, 1.0)
    assert 111_000 < dist < 111_400, dist


def test_haversine_same_point_zero():
    assert _haversine(106.8, -6.2, 106.8, -6.2) == 0.0


def test_radius_bbox_contains_center():
    w, s, e, n = _radius_bbox(106.8, -6.2, 1000)
    assert w < 106.8 < e
    assert s < -6.2 < n


def test_representative_point_geojson():
    point = _representative_point(
        {"type": "Point", "coordinates": [106.8, -6.2]}
    )
    assert point == (106.8, -6.2)


def test_representative_point_esri():
    esri_point = _representative_point({"x": 106.8, "y": -6.2})
    assert esri_point == (106.8, -6.2)
    polygon = _representative_point(
        {"rings": [[[106.7, -6.3], [106.9, -6.3], [106.9, -6.1], [106.7, -6.1], [106.7, -6.3]]]}
    )
    assert polygon is not None
    assert 106.7 < polygon[0] < 106.9
    assert -6.3 < polygon[1] < -6.1


def test_representative_point_empty():
    assert _representative_point(None) is None
    assert _representative_point({"type": "GeometryCollection", "geometries": []}) is None
    assert _representative_point({"rings": []}) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("All geocoding helper checks passed.")