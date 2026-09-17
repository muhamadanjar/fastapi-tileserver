"""Reference analysis operations beyond intersection.

Every operation returns the same FeatureCollection contract as
``intersect_reference`` (features, summary, warnings, measurement) so stored
artifacts, tables and exports stay operation-agnostic.
"""
from collections import defaultdict
import json

from shapely import get_num_coordinates
from shapely.geometry import mapping

from app.analysis.reference_intersection import (
    by_dimension,
    category_value,
    intersect_reference,
    measure,
    properties,
)

OPERATIONS = ("intersect", "clip", "difference", "spatial_join")
MEASUREMENT = {
    "area_crs": "EPSG:6933",
    "length": "WGS84 geodesic segments",
    "topology": "2D EPSG:4326; exact boundary; no snapping",
    "percentage": "full source feature per dimension",
}
UNMATCHED_LABEL = "Tanpa acuan"
OUTSIDE_LABEL = "Di luar acuan"


def _columns(reference, category_field, attributes):
    missing = set([category_field, *attributes]) - set(reference.columns)
    if missing or reference.geometry.name in [category_field, *attributes]:
        raise ValueError(f"Kolom acuan tidak tersedia: {', '.join(sorted(missing)) or 'geometry'}")


class _Output:
    """Shared feature/summary accumulation with the same size guards as intersection."""

    def __init__(self, run_id, max_results, max_bytes, max_vertices):
        self.run_id = run_id
        self.features = []
        self.bounds = None
        self.bytes = 0
        self.vertices = 0
        self.totals = {}
        self.max_results = max_results
        self.max_bytes = max_bytes
        self.max_vertices = max_vertices

    def add(self, row, geom, dim, source_dimension, relation, category, ref_id, source_attributes, reference_attributes, denominator, label=None):
        amount = measure(geom, dim)
        category_label = label if label is not None else ("Kategori belum diisi" if category is None else str(category))
        props = {
            "src_id": f"{self.run_id}:{row}", "src_row": row,
            "label": f"Objek {row + 1}", "ref_id": ref_id,
            "category": category, "category_label": category_label,
            "category_missing": category is None and label is None,
            "source_dimension": source_dimension, "dimension": dim,
            "relation": relation, "overlap": False,
            "area_m2": amount if dim == 2 else 0.0,
            "area_ha": amount / 10000 if dim == 2 else 0.0,
            "length_m": amount if dim == 1 else 0.0,
            "point_count": int(amount) if dim == 0 else 0,
            "pct": (100 * amount / denominator if denominator else 0.0) if source_dimension > 0 else None,
            "source_attributes": source_attributes,
            "reference_attributes": reference_attributes,
        }
        west, south, east, north = geom.bounds
        self.bounds = [west, south, east, north] if self.bounds is None else [min(self.bounds[0], west), min(self.bounds[1], south), max(self.bounds[2], east), max(self.bounds[3], north)]
        feature = {"type": "Feature", "geometry": mapping(geom), "properties": props}
        self.bytes += len(json.dumps(feature, ensure_ascii=False).encode())
        self.vertices += int(get_num_coordinates(geom))
        if self.bytes > self.max_bytes or self.vertices > self.max_vertices:
            raise ValueError("Ukuran atau kompleksitas hasil melebihi batas. Perkecil dataset unggahan.")
        if len(self.features) >= self.max_results:
            raise ValueError(f"Hasil melebihi batas {self.max_results:,} baris. Perkecil dataset unggahan.")
        self.features.append(feature)
        key = (json.dumps(category, sort_keys=True, ensure_ascii=False), source_dimension, dim, relation)
        total = self.totals.setdefault(key, {
            "category": category, "category_label": category_label,
            "source_dimension": source_dimension, "dimension": dim, "relation": relation,
            "object_count": 0, "area_m2": 0.0, "area_ha": 0.0, "length_m": 0.0,
            "point_count": 0, "overlap": False,
        })
        total["object_count"] += 1
        total["area_m2"] += amount if dim == 2 else 0.0
        total["area_ha"] = total["area_m2"] / 10000
        total["length_m"] += amount if dim == 1 else 0.0
        total["point_count"] += int(amount) if dim == 0 else 0
        return feature

    def result(self, warnings):
        return {
            "type": "FeatureCollection", "features": self.features,
            **({"bbox": self.bounds} if self.bounds else {}),
            "summary": list(self.totals.values()), "warnings": warnings,
            "measurement": MEASUREMENT,
        }


def clip_reference(source, reference, category_field, attributes, run_id, max_results=100_000, max_output_bytes=250 * 1024 * 1024, max_output_vertices=10_000_000):
    """Cut source geometry inside the reference. Line/point contacts are not carried."""
    # ponytail: reuse the full intersection engine, then drop boundary contacts;
    # add a dedicated interior-only pass if the wasted boundary work ever matters.
    result = intersect_reference(source, reference, category_field, attributes, run_id, max_results, max_output_bytes, max_output_vertices)
    result["features"] = [f for f in result["features"] if f["properties"]["relation"] == "intersection"]
    result["summary"] = [s for s in result["summary"] if s["relation"] == "intersection"]
    if not result["features"]:
        result.pop("bbox", None)
    return result


def difference_reference(source, reference, category_field, attributes, run_id, max_results=100_000, max_output_bytes=250 * 1024 * 1024, max_output_vertices=10_000_000):
    """Parts of the source outside every reference polygon."""
    source_props = properties(source)
    output = _Output(run_id, max_results, max_output_bytes, max_output_vertices)
    index = reference.sindex
    for row, original in enumerate(source.geometry):
        dimensions = by_dimension(original)
        denominators = {dim: measure(geom, dim) for dim, geom in dimensions.items()}
        remaining = dict(dimensions)
        for candidate in index.query(original, predicate="intersects"):
            polygon = reference.geometry.iloc[int(candidate)]
            for dim, geom in list(remaining.items()):
                cut = geom.difference(polygon)
                if cut.is_empty:
                    remaining.pop(dim)
                else:
                    remaining[dim] = cut
        for dim, geom in remaining.items():
            for part_dim, part in by_dimension(geom).items():
                output.add(row, part, part_dim, dim, "difference", None, None, source_props[row], {}, denominators[dim], label=OUTSIDE_LABEL)
    warning = [] if output.features else ["Tidak ada bagian sumber yang berada di luar acuan."]
    return output.result(warning)


def spatial_join_reference(source, reference, category_field, attributes, run_id, max_results=100_000, max_output_bytes=250 * 1024 * 1024, max_output_vertices=10_000_000):
    """Attach reference attributes to whole source features without cutting geometry."""
    _columns(reference, category_field, attributes)
    source_props, reference_props = properties(source), properties(reference)
    output = _Output(run_id, max_results, max_output_bytes, max_output_vertices)
    index = reference.sindex
    unmatched = 0
    multi = 0
    missing_categories = False
    for row, original in enumerate(source.geometry):
        dimensions = by_dimension(original)
        denominators = {dim: measure(geom, dim) for dim, geom in dimensions.items()}
        candidates = [int(c) for c in index.query(original, predicate="intersects")]
        if len(candidates) > 1:
            multi += 1
        if not candidates:
            unmatched += 1
            for dim, geom in dimensions.items():
                for part_dim, part in by_dimension(geom).items():
                    output.add(row, part, part_dim, dim, "spatial_join", None, None, source_props[row], {}, denominators[dim], label=UNMATCHED_LABEL)
            continue
        for candidate in candidates:
            attrs = reference_props[candidate]
            category = category_value(attrs.get(category_field))
            missing_categories |= category is None
            reference_attributes = {name: attrs.get(name) for name in attributes}
            for dim, geom in dimensions.items():
                for part_dim, part in by_dimension(geom).items():
                    output.add(row, part, part_dim, dim, "spatial_join", category, str(candidate), source_props[row], reference_attributes, denominators[dim])
    warnings = []
    if unmatched:
        warnings.append(f"{unmatched} objek sumber tidak beririsan dengan acuan dan ditandai {UNMATCHED_LABEL}.")
    if missing_categories:
        warnings.append("Kategori kosong ditampilkan sebagai Kategori belum diisi.")
    if multi:
        warnings.append("Objek sumber dapat muncul lebih dari sekali bila beririsan dengan beberapa poligon acuan; luasan per acuan dapat terhitung berulang.")
    return output.result(warnings)


def run_reference_operation(operation, source, reference, category_field, attributes, run_id, max_results=100_000, max_output_bytes=250 * 1024 * 1024, max_output_vertices=10_000_000):
    if operation == "intersect":
        return intersect_reference(source, reference, category_field, attributes, run_id, max_results, max_output_bytes, max_output_vertices)
    if operation == "clip":
        return clip_reference(source, reference, category_field, attributes, run_id, max_results, max_output_bytes, max_output_vertices)
    if operation == "difference":
        return difference_reference(source, reference, category_field, attributes, run_id, max_results, max_output_bytes, max_output_vertices)
    if operation == "spatial_join":
        return spatial_join_reference(source, reference, category_field, attributes, run_id, max_results, max_output_bytes, max_output_vertices)
    raise ValueError(f"Operasi analisis tidak dikenal: {operation}")
