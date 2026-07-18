import pytest

from app.domain.models import Feature, Project
from app.infrastructure.services.project_export_service import (
    InvalidStoredGeometryError, build_feature_collection, export_csv,
    flatten_attributes, shp_safe_columns,
)

SCHEMA = [
    {"name": "nama", "label": "Nama", "type": "text"},
    {"name": "fasilitas", "label": "Fasilitas", "type": "multiselect", "options": ["pju", "drainase"]},
    {"name": "aktif", "label": "Aktif", "type": "checkbox"},
]


def _project(**kw):
    defaults = dict(id="p1", name="Survey", geometry_type="point", form_schema=SCHEMA)
    defaults.update(kw)
    return Project(**defaults)


def _feature(**kw):
    defaults = dict(
        id="f1", project_id="p1",
        geometry={"type": "Point", "coordinates": [106.8, -6.2]},
        attributes={"nama": "Titik A", "fasilitas": ["pju", "drainase"], "aktif": True},
        created_by="anjar",
    )
    defaults.update(kw)
    return Feature(**defaults)


def test_flatten_multiselect_joined():
    flat = flatten_attributes(SCHEMA, _feature().attributes)
    assert flat["fasilitas"] == "pju;drainase"
    assert flat["aktif"] is True
    assert flat["nama"] == "Titik A"


def test_feature_collection_shape():
    fc = build_feature_collection(_project(), [_feature()])
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1
    f = fc["features"][0]
    assert f["geometry"]["type"] == "Point"
    assert f["properties"]["_id"] == "f1"
    assert f["properties"]["nama"] == "Titik A"


def test_shp_safe_columns_truncate_and_dedup():
    cols = shp_safe_columns(["kondisi_jalan_utama", "kondisi_jalan_kedua", "nama"])
    assert all(len(v) <= 10 for v in cols.values())
    assert len(set(cols.values())) == 3
    assert cols["nama"] == "nama"


def test_export_csv_point_has_lon_lat_and_wkt():
    csv_text = export_csv(_project(), [_feature()])
    header = csv_text.splitlines()[0].split(",")
    assert "wkt" in header and "longitude" in header and "latitude" in header
    row = csv_text.splitlines()[1]
    assert "POINT" in row and "Titik A" in row


def test_export_csv_line_has_no_lon_lat():
    p = _project(geometry_type="line")
    f = _feature(geometry={"type": "LineString", "coordinates": [[1, 1], [2, 2]]})
    header = export_csv(p, [f]).splitlines()[0].split(",")
    assert "longitude" not in header and "wkt" in header


def test_export_csv_formula_values_are_prefixed():
    f = _feature(attributes={"nama": "=cmd|' /C calc'!A0", "fasilitas": ["pju"], "aktif": False})
    csv_text = export_csv(_project(), [f])
    assert "'=cmd" in csv_text
    assert "\n=cmd" not in csv_text


def test_export_csv_invalid_stored_geometry_raises_typed_error():
    f = _feature(geometry={"type": "Point"})
    with pytest.raises(InvalidStoredGeometryError):
        export_csv(_project(), [f])
