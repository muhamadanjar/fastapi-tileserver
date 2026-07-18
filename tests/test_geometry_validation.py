import pytest
from app.domain.geometry_validation import GeometryValidationError, validate_geometry

POINT = {"type": "Point", "coordinates": [106.8, -6.2]}
LINE = {"type": "LineString", "coordinates": [[106.8, -6.2], [106.9, -6.25]]}
POLYGON = {"type": "Polygon", "coordinates": [[[106.8, -6.2], [106.9, -6.2], [106.9, -6.3], [106.8, -6.2]]]}


def test_valid_point():
    validate_geometry(POINT, "point")

def test_valid_line():
    validate_geometry(LINE, "line")

def test_valid_polygon():
    validate_geometry(POLYGON, "polygon")

def test_type_mismatch_rejected():
    with pytest.raises(GeometryValidationError):
        validate_geometry(POINT, "polygon")

def test_multi_geometry_rejected():
    multi = {"type": "MultiPoint", "coordinates": [[106.8, -6.2]]}
    with pytest.raises(GeometryValidationError):
        validate_geometry(multi, "point")

def test_out_of_range_coordinates_rejected():
    bad = {"type": "Point", "coordinates": [206.8, -96.2]}
    with pytest.raises(GeometryValidationError):
        validate_geometry(bad, "point")

def test_self_intersecting_polygon_rejected():
    bowtie = {"type": "Polygon", "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]}
    with pytest.raises(GeometryValidationError):
        validate_geometry(bowtie, "polygon")

def test_garbage_geojson_rejected():
    with pytest.raises(GeometryValidationError):
        validate_geometry({"type": "Point"}, "point")
