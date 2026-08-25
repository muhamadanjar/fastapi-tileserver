"""GeoJSON geometry validation for survey Features (WGS84, simple geometries only)."""
from shapely.errors import GEOSException
from shapely.geometry import shape

GEOJSON_TYPE_FOR = {"point": "Point", "line": "LineString", "polygon": "Polygon"}


class GeometryValidationError(ValueError):
    pass


def _iter_positions(coords):
    if isinstance(coords, (list, tuple)) and coords and isinstance(coords[0], (int, float)):
        yield coords
    elif isinstance(coords, (list, tuple)):
        for c in coords:
            yield from _iter_positions(c)


def validate_geometry(geometry: dict, geometry_type: str) -> None:
    expected = GEOJSON_TYPE_FOR.get(geometry_type)
    if expected is None:
        raise GeometryValidationError(f"unknown project geometry_type {geometry_type!r}")
    if not isinstance(geometry, dict) or geometry.get("type") != expected:
        raise GeometryValidationError(
            f"geometry type must be {expected!r} for this project, got {geometry.get('type')!r}"
        )
    coords = geometry.get("coordinates")
    if coords is None:
        raise GeometryValidationError("geometry has no coordinates")
    for pos in _iter_positions(coords):
        if len(pos) < 2 or not (-180 <= pos[0] <= 180) or not (-90 <= pos[1] <= 90):
            raise GeometryValidationError(f"coordinate out of WGS84 range: {pos}")
    try:
        geom = shape(geometry)
    except (GEOSException, ValueError, TypeError) as exc:
        raise GeometryValidationError(f"invalid geometry: {exc}") from exc
    if geom.is_empty or not geom.is_valid:
        raise GeometryValidationError("geometry is empty or invalid (self-intersection?)")
