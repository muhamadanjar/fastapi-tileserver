import geopandas as gpd
from shapely.geometry import LineString, Point

from app.infrastructure.services.shapefile_import_service import POSTGIS_WKB_EXPRESSION
from app.infrastructure.services.tiling_service import _force_2d_geometries
from app.infrastructure.services.map_renderer import _normalize_style_geometry_keys


def test_vector_tiling_discards_z_ordinate_from_derived_geometries():
    source = gpd.GeoDataFrame(geometry=[Point(106.7, -6.5, 12), LineString([(106.7, -6.5, 1), (106.8, -6.6, 2)])], crs="EPSG:4326")

    result = _force_2d_geometries(source)

    assert source.geometry.iloc[0].has_z
    assert not any(geometry.has_z for geometry in result.geometry)


def test_postgis_insert_forces_geometry_to_2d():
    assert "ST_Force2D" in POSTGIS_WKB_EXPRESSION


def test_persisted_z_style_keys_are_normalized_for_retry():
    style = {"LineString Z": {"strokeColor": "#3388ff"}, "Point ZM": {"pointRadius": 5}}

    assert _normalize_style_geometry_keys(style) == {
        "LineString": {"strokeColor": "#3388ff"},
        "Point": {"pointRadius": 5},
    }
