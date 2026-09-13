"""Bounded SHP input and self-contained, private analysis artifacts."""
import csv
import json
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

import geopandas as gpd
import pyogrio
from shapely.geometry import shape

from app.analysis.reference_intersection import parts, DIMENSIONS, validate_frame


def read_shapefile_archive(archive: Path, destination: Path, settings):
    try:
        with zipfile.ZipFile(archive) as zipped:
            members = [m for m in zipped.infolist() if not m.is_dir()]
            if len(members) > 100:
                raise ValueError("ZIP berisi terlalu banyak berkas.")
            if sum(m.file_size for m in members) > settings.ANALYSIS_MAX_EXTRACTED_BYTES:
                raise ValueError("Ukuran ZIP setelah ekstraksi melebihi batas.")
            names = set()
            for member in members:
                path = PurePosixPath(member.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in member.filename or stat.S_ISLNK(member.external_attr >> 16):
                    raise ValueError("ZIP mengandung path yang tidak aman.")
                lowered = member.filename.casefold()
                if lowered in names:
                    raise ValueError("ZIP mengandung nama berkas duplikat.")
                names.add(lowered)
            shps = [m for m in members if m.filename.lower().endswith(".shp")]
            if len(shps) != 1:
                raise ValueError("Unggah satu ZIP berisi tepat satu dataset SHP. Pisahkan setiap dataset.")
            shp = shps[0]
            stem = str(PurePosixPath(shp.filename).with_suffix("")).casefold()
            for suffix in (".shx", ".dbf", ".prj"):
                if stem + suffix not in names:
                    raise ValueError(f"Berkas pendamping {suffix} tidak ditemukan.")
            destination.mkdir(parents=True, exist_ok=True)
            # Normalize matching component names, avoiding case-sensitive driver surprises.
            for member in members:
                path = PurePosixPath(member.filename)
                if str(path.with_suffix("")).casefold() == stem and path.suffix.lower() in {".shp", ".shx", ".dbf", ".prj", ".cpg"}:
                    target = destination / ("input" + path.suffix.lower())
                    with zipped.open(member) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
            source = destination / "input.shp"
            count = int(pyogrio.read_info(source)["features"])
            if count > settings.ANALYSIS_MAX_FEATURES:
                raise ValueError(f"Maksimal {settings.ANALYSIS_MAX_FEATURES:,} fitur; ditemukan {count:,}.")
            return validate_frame(gpd.read_file(source), max_features=settings.ANALYSIS_MAX_FEATURES, max_vertices=settings.ANALYSIS_MAX_VERTICES)
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError("ZIP tidak dapat dibaca atau dilindungi kata sandi.") from exc


def write_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def csv_value(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row)) or ["message"]
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(value) for key, value in row.items()})


def export_results(directory: Path, result):
    """Exports are made by the worker once, never concurrently by download requests."""
    write_json(directory / "result.geojson", result)
    write_csv(directory / "details.csv", [f["properties"] for f in result["features"]])
    write_csv(directory / "summary.csv", result["summary"])
    with zipfile.ZipFile(directory / "csv.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in ("details.csv", "summary.csv"):
            bundle.write(directory / name, name)
    shp_dir = directory / "shp"
    shp_dir.mkdir(exist_ok=True)
    grouped = {0: [], 1: [], 2: []}
    # SHP columns are <=10 chars. Full attributes/IDs also live in lossless JSON.
    fields = {"src_id": "src_id", "src_row": "src_row", "ref_id": "ref_id", "category_label": "category", "relation": "relation", "overlap": "overlap", "area_m2": "area_m2", "area_ha": "area_ha", "length_m": "length_m", "point_count": "pt_count", "pct": "pct"}
    for result_row, feature in enumerate(result["features"]):
        props = feature["properties"]
        for geometry in parts(shape(feature["geometry"])):
            row = {target: props[key] for key, target in fields.items()}
            row.update(result_row=result_row, geometry=geometry)
            grouped[DIMENSIONS[geometry.geom_type]].append(row)
    attribute_fields = {}
    for row in grouped.values():
        for record in row:
            props = result["features"][record["result_row"]]["properties"]
            for side in ("source_attributes", "reference_attributes"):
                for name, value in props[side].items():
                    key = f"{side}.{name}"
                    if key not in attribute_fields:
                        attribute_fields[key] = f"attr{len(attribute_fields):05d}"
                    record[attribute_fields[key]] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
    if len(attribute_fields) > 200:
        raise ValueError("Terlalu banyak atribut untuk ekspor SHP; pilih maksimal 200 atribut gabungan.")
    for dim, name in ((0, "points"), (1, "lines"), (2, "polygons")):
        if grouped[dim]:
            gpd.GeoDataFrame(grouped[dim], crs=4326).to_file(shp_dir / f"{name}.shp", driver="ESRI Shapefile", encoding="UTF-8")
    write_json(shp_dir / "fields.json", {"metrics": fields, "attributes": attribute_fields, "notes": "SHP string values may be truncated at 254 bytes. Full values and result_row mapping are in result.geojson."})
    with zipfile.ZipFile(directory / "shp.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(shp_dir.iterdir()):
            bundle.write(path, path.name)
        bundle.write(directory / "result.geojson", "result.geojson")
