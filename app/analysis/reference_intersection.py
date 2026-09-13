"""Dimension-aware overlay with pair traceability and per-category union totals."""
from collections import defaultdict
import json
import math

import geopandas as gpd
import numpy as np
from pyproj import Geod, Transformer
from shapely import force_2d, get_coordinates, get_num_coordinates
from shapely.geometry import mapping
from shapely.ops import transform, unary_union
from shapely.validation import explain_validity

GEOD = Geod(ellps="WGS84")
AREA = Transformer.from_crs(4326, 6933, always_xy=True)
DIMENSIONS = {"Point": 0, "LineString": 1, "LinearRing": 1, "Polygon": 2}


def parts(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type in DIMENSIONS:
        yield geometry
    else:
        for child in geometry.geoms:
            yield from parts(child)


def by_dimension(geometry):
    groups = defaultdict(list)
    for part in parts(geometry):
        groups[DIMENSIONS[part.geom_type]].append(part)
    return {dim: unary_union(items) for dim, items in groups.items()}


def measure(geometry, dimension):
    if geometry.is_empty:
        return 0.0
    if dimension == 2:
        return float(transform(AREA.transform, geometry).area)
    if dimension == 1:
        return float(GEOD.geometry_length(geometry))
    return float(sum(1 for _ in parts(geometry)))


def validate_frame(frame, *, label="Unggahan", max_features=None, max_vertices=1_000_000, polygon_only=False):
    if frame.crs is None:
        raise ValueError(f"{label}: CRS tidak dikenali. Sertakan berkas .prj yang benar.")
    if frame.empty:
        raise ValueError(f"{label}: dataset tidak memiliki fitur.")
    if max_features is not None and len(frame) > max_features:
        raise ValueError(f"{label}: maksimal {max_features:,} fitur; ditemukan {len(frame):,}.")
    if not frame.columns.is_unique:
        raise ValueError(f"{label}: nama kolom atribut harus unik.")
    vertices = int(sum(get_num_coordinates(g) for g in frame.geometry if g is not None))
    if vertices > max_vertices:
        raise ValueError(f"{label}: melebihi batas {max_vertices:,} titik penyusun geometri.")
    for row, geom in enumerate(frame.geometry):
        if geom is None or geom.is_empty or not geom.is_valid:
            reason = explain_validity(geom) if geom is not None else "geometri kosong"
            raise ValueError(f"{label}, Objek {row + 1}: {reason}")
        if not np.isfinite(get_coordinates(geom)).all():
            raise ValueError(f"{label}, Objek {row + 1}: koordinat tidak valid.")
        if polygon_only and geom.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"{label}: acuan harus Polygon/MultiPolygon.")
    result = frame.to_crs(4326).reset_index(drop=True)
    for row, geom in enumerate(result.geometry):
        west, south, east, north = geom.bounds
        if not all(math.isfinite(v) for v in geom.bounds) or west < -180 or east > 180 or south < -86 or north > 86 or east - west > 180:
            raise ValueError(f"{label}, Objek {row + 1}: di luar domain pengukuran (86°S–86°N; pisahkan lintasan antimeridian).")
        if not geom.is_valid:
            raise ValueError(f"{label}, Objek {row + 1}: tidak valid setelah transformasi CRS.")
    result.geometry = result.geometry.map(force_2d)
    return result


def properties(frame):
    # GeoPandas handles dates, nulls and numpy scalars consistently with GeoJSON.
    return [f["properties"] for f in json.loads(frame.to_json(drop_id=True))["features"]]


def category_value(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return value


def intersect_reference(source, reference, category_field, attributes, run_id, max_results=100_000, max_output_bytes=250 * 1024 * 1024, max_output_vertices=10_000_000):
    missing = set([category_field, *attributes]) - set(reference.columns)
    if missing or reference.geometry.name in [category_field, *attributes]:
        raise ValueError(f"Kolom acuan tidak tersedia: {', '.join(sorted(missing)) or 'geometry'}")
    source_props, reference_props = properties(source), properties(reference)
    features = []
    bounds = None
    output_bytes = 0
    output_vertices = 0
    totals = {}
    missing_categories = False
    index = reference.sindex
    for row, original in enumerate(source.geometry):
        dimensions = by_dimension(original)
        denominators = {dim: measure(geom, dim) for dim, geom in dimensions.items()}
        buckets = defaultdict(list)
        category_labels = {}
        row_features = []
        coverage_by_dimension = defaultdict(list)
        for candidate in index.query(original, predicate="intersects", sort=True):
            candidate = int(candidate)
            polygon = reference.geometry.iloc[candidate]
            attrs = reference_props[candidate]
            category = category_value(attrs.get(category_field))
            missing_categories |= category is None
            key = json.dumps(category, sort_keys=True, ensure_ascii=False)
            label = "Kategori belum diisi" if category is None else str(category)
            category_labels[key] = (category, label)
            for source_dim, source_geometry in dimensions.items():
                intersection = source_geometry.intersection(polygon)
                if intersection.is_empty:
                    continue
                segments = []
                if source_dim == 1:
                    boundary = intersection.intersection(polygon.boundary)
                    interior = intersection.difference(boundary)
                    segments.extend((dim, geom, "intersection") for dim, geom in by_dimension(interior).items())
                    segments.extend((dim, geom, "boundary") for dim, geom in by_dimension(boundary).items())
                else:
                    for dim, geom in by_dimension(intersection).items():
                        if source_dim == 0:
                            boundary = geom.intersection(polygon.boundary)
                            interior = geom.difference(boundary)
                            if not interior.is_empty:
                                segments.append((0, interior, "intersection"))
                            if not boundary.is_empty:
                                segments.append((0, boundary, "boundary"))
                        else:
                            segments.append((dim, geom, "intersection" if dim == source_dim else "boundary"))
                for dim, geom, relation in segments:
                    amount = measure(geom, dim)
                    denominator = denominators[source_dim]
                    metric = amount if dim == source_dim else 0.0
                    pct = 100 * metric / denominator if denominator else 0.0
                    props = {
                        "src_id": f"{run_id}:{row}", "src_row": row,
                        "label": f"Objek {row + 1}", "ref_id": str(candidate),
                        "category": category, "category_label": label,
                        "category_missing": category is None,
                        "source_dimension": source_dim, "dimension": dim,
                        "relation": relation, "overlap": False,
                        "area_m2": amount if dim == 2 else 0.0,
                        "area_ha": amount / 10000 if dim == 2 else 0.0,
                        "length_m": amount if dim == 1 else 0.0,
                        "point_count": int(amount) if dim == 0 else 0,
                        "pct": pct if source_dim > 0 else None,
                        "source_attributes": source_props[row],
                        "reference_attributes": {name: attrs.get(name) for name in attributes},
                    }
                    west, south, east, north = geom.bounds
                    bounds = [west, south, east, north] if bounds is None else [min(bounds[0], west), min(bounds[1], south), max(bounds[2], east), max(bounds[3], north)]
                    feature = {"type": "Feature", "geometry": mapping(geom), "properties": props}
                    output_bytes += len(json.dumps(feature, ensure_ascii=False).encode())
                    output_vertices += int(get_num_coordinates(geom))
                    if output_bytes > max_output_bytes or output_vertices > max_output_vertices:
                        raise ValueError("Ukuran atau kompleksitas hasil melebihi batas. Perkecil dataset unggahan.")
                    features.append(feature)
                    row_features.append(features[-1])
                    if len(features) > max_results:
                        raise ValueError(f"Hasil melebihi batas {max_results:,} irisan. Perkecil dataset unggahan.")
                    buckets[(key, source_dim, dim, relation)].append(geom)
                    if dim == source_dim:
                        coverage_by_dimension[dim].append(geom)
        # A union comparison detects overlap without an O(n²) pair loop.
        overlap_dimensions = set()
        for dim, geoms in coverage_by_dimension.items():
            separate = sum(measure(g, dim) for g in geoms)
            unique = measure(unary_union(geoms), dim)
            if separate > unique + max(1e-8, unique * 1e-9):
                overlap_dimensions.add(dim)
        for feature in row_features:
            feature["properties"]["overlap"] = feature["properties"]["dimension"] in overlap_dimensions
        # Interior wins over boundary within the same category/dimension. Otherwise
        # a line on one polygon's edge but inside its same-category neighbour would
        # appear twice in the category totals.
        normalized = {key: unary_union(geoms) for key, geoms in buckets.items()}
        for (key, source_dim, dim, relation), geometry in list(normalized.items()):
            interior_key = (key, source_dim, dim, "intersection")
            if relation == "boundary" and interior_key in normalized:
                normalized[(key, source_dim, dim, relation)] = geometry.difference(normalized[interior_key])
        for (key, source_dim, dim, relation), geometry in normalized.items():
            if geometry.is_empty:
                continue
            amount = measure(geometry, dim)
            total_key = (key, source_dim, dim, relation)
            if total_key not in totals:
                category, label = category_labels[key]
                totals[total_key] = {
                    "category": category, "category_label": label,
                    "source_dimension": source_dim, "dimension": dim,
                    "relation": relation, "object_count": 0,
                    "area_m2": 0.0, "area_ha": 0.0, "length_m": 0.0,
                    "point_count": 0, "overlap": False,
                }
            total = totals[total_key]
            total["object_count"] += 1
            total["area_m2"] += amount if dim == 2 else 0.0
            total["area_ha"] = total["area_m2"] / 10000
            total["length_m"] += amount if dim == 1 else 0.0
            total["point_count"] += int(amount) if dim == 0 else 0
            total["overlap"] |= dim in overlap_dimensions
    warnings = ["Kategori kosong ditampilkan sebagai Kategori belum diisi."] if missing_categories else []
    if any(f["properties"]["overlap"] for f in features):
        warnings.append("Acuan tumpang tindih: rincian per pasangan dan kategori berbeda dapat menghitung bagian yang sama. Persentase dapat melebihi 100% jika dijumlahkan.")
    return {
        "type": "FeatureCollection", "features": features,
        **({"bbox": bounds} if bounds else {}),
        "summary": list(totals.values()), "warnings": warnings,
        "measurement": {"area_crs": "EPSG:6933", "length": "WGS84 geodesic segments", "topology": "2D EPSG:4326; exact boundary; no snapping", "percentage": "full source feature per dimension"},
    }
