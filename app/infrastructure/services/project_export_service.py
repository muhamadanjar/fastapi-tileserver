"""Build FeatureCollections and flat exports (CSV/SHP) from survey Features."""
import csv
import io
import zipfile
from pathlib import Path

from shapely.geometry import shape

from app.domain.models import Feature, Project


class InvalidStoredGeometryError(ValueError):
    """A Feature's stored geometry cannot be parsed as GeoJSON."""


def _shape_or_error(feature: Feature):
    try:
        return shape(feature.geometry)
    except Exception as exc:
        raise InvalidStoredGeometryError(
            f"feature {feature.id} has invalid stored geometry: {exc}"
        ) from exc


def _csv_safe(value):
    # Guard against spreadsheet formula injection (values opened in Excel/Sheets).
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def flatten_attributes(schema: list, attributes: dict, base_url: str = "") -> dict:
    flat = {}
    for field in schema:
        name = field["name"]
        value = attributes.get(name)
        if value is None:
            flat[name] = None
        elif field.get("type") == "multiselect" and isinstance(value, list):
            flat[name] = ";".join(str(v) for v in value)
        elif field.get("type") == "file" and isinstance(value, str) and base_url:
            flat[name] = f"{base_url}/attachments/{value}"
        else:
            flat[name] = value
    return flat


def build_feature_collection(project: Project, features: list[Feature], base_url: str = "") -> dict:
    out = []
    for f in features:
        props = flatten_attributes(project.form_schema, f.attributes, base_url)
        props["_id"] = f.id
        props["_created_by"] = f.created_by
        props["_created_at"] = f.created_at.isoformat() if f.created_at else None
        out.append({"type": "Feature", "id": f.id, "geometry": f.geometry, "properties": props})
    return {"type": "FeatureCollection", "features": out}


def shp_safe_columns(names: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for name in names:
        candidate = name[:10]
        i = 1
        while candidate in used:
            suffix = f"_{i}"
            candidate = name[: 10 - len(suffix)] + suffix
            i += 1
        mapping[name] = candidate
        used.add(candidate)
    return mapping


def export_csv(project: Project, features: list[Feature]) -> str:
    field_names = [f["name"] for f in project.form_schema]
    header = ["id"] + field_names + ["created_by", "created_at", "wkt"]
    is_point = project.geometry_type == "point"
    if is_point:
        header += ["longitude", "latitude"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for f in features:
        flat = flatten_attributes(project.form_schema, f.attributes)
        geom = _shape_or_error(f)
        row = [f.id] + [_csv_safe(flat.get(n)) for n in field_names] + [
            f.created_by, f.created_at.isoformat() if f.created_at else None, geom.wkt,
        ]
        if is_point:
            row += [geom.x, geom.y]
        writer.writerow(row)
    return buf.getvalue()


def export_shp_zip(project: Project, features: list[Feature], dest_dir: Path) -> Path:
    import geopandas as gpd

    field_names = [f["name"] for f in project.form_schema]
    colmap = shp_safe_columns(field_names + ["created_by"])
    records, geoms = [], []
    for f in features:
        flat = flatten_attributes(project.form_schema, f.attributes)
        rec = {colmap[n]: flat.get(n) for n in field_names}
        rec[colmap["created_by"]] = f.created_by
        records.append(rec)
        geoms.append(_shape_or_error(f))
    gdf = gpd.GeoDataFrame(records, geometry=geoms, crs="EPSG:4326")
    shp_dir = dest_dir / "shp"
    shp_dir.mkdir(parents=True, exist_ok=True)
    shp_path = shp_dir / f"{project.id}.shp"
    gdf.to_file(shp_path, driver="ESRI Shapefile")
    zip_path = dest_dir / f"{project.name.replace(' ', '_')}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for part in shp_dir.iterdir():
            zf.write(part, part.name)
    return zip_path
