"""Validated, pairwise polygon intersection with equal-area measurements."""

import json
import math
from dataclasses import dataclass
from numbers import Integral, Real

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.validation import explain_validity

AREA_CRS = "EPSG:6933"
AREA_FIELDS = [
    "src_a_id", "src_b_id", "src_a_row", "src_b_row",
    "area_m2", "area_ha", "pct_a", "pct_b",
]


def area_option_errors(request: dict) -> list[str]:
    if request.get("calculate_area"):
        if request.get("operation") != "intersection":
            return ["calculate_area is only supported for polygon intersection"]
    elif request.get("source_id_field_a") is not None or request.get("source_id_field_b") is not None:
        return ["source_id_field_a/source_id_field_b require calculate_area=true"]
    return []


@dataclass
class AreaInput:
    source: gpd.GeoDataFrame
    projected: gpd.GeoDataFrame
    ids: list[str]
    id_field: str | None
    side: str

    def snapshot(self, layer_id: str) -> dict:
        # to_json handles numpy scalars and missing attribute values. Keep all
        # source attributes, independent of the result attribute selection.
        collection = json.loads(self.source.to_json(to_wgs84=True, drop_id=True, default=str))
        for row, feature in enumerate(collection["features"]):
            feature["id"] = self.ids[row]
            feature["source_row"] = row
        return {
            "layer_id": layer_id,
            "id_field": self.id_field,
            "source_crs": self.source.crs.to_string(),
            **collection,
        }


def prepare_area_input(
    frame: gpd.GeoDataFrame, side: str, id_field: str | None, run_id: str,
    selected_attributes: dict | None = None,
) -> AreaInput:
    """Validate without repairing or dropping input features, then project."""
    label = f"Layer {side.upper()}"
    source = frame.copy().reset_index(drop=True)
    if not source.columns.is_unique:
        raise ValueError(f"{label}: duplicate attribute column names")
    if source.crs is None:
        raise ValueError(f"{label}: CRS is required for area calculation")
    if id_field is not None:
        if id_field not in source.columns or id_field == source.geometry.name:
            raise ValueError(f"{label}: ID field {id_field!r} is not an attribute")
        ids = []
        for row, value in enumerate(source[id_field]):
            if isinstance(value, str) and value.strip():
                identifier = value
            elif isinstance(value, Integral) and not isinstance(value, (bool, np.bool_)):
                identifier = str(value)
            elif isinstance(value, Real) and not isinstance(value, (bool, np.bool_)) and math.isfinite(value):
                identifier = str(value)
            else:
                raise ValueError(f"{label} row {row}: ID must be a non-empty string or finite number")
            ids.append(identifier)
        duplicate = (
            pd.Series(ids, dtype="str").duplicated(keep=False)
            | source[id_field].duplicated(keep=False)
        )
        if duplicate.any():
            repeated = sorted(set(pd.Series(ids)[duplicate]))
            raise ValueError(f"{label}: duplicate source IDs: {repeated}")
    else:
        ids = [f"{run_id}:{side}:{row}" for row in range(len(source))]

    errors = []
    for row, geometry in enumerate(source.geometry):
        reason = None
        if geometry is None or geometry.is_empty:
            reason = "null or empty geometry"
        elif geometry.geom_type not in ("Polygon", "MultiPolygon"):
            reason = "calculate_area requires Polygon or MultiPolygon"
        elif not geometry.is_valid:
            reason = explain_validity(geometry)
        elif not np.isfinite(geometry.bounds).all():
            reason = "non-finite coordinates"
        if reason:
            errors.append(f"{label} source ID {ids[row]!r} (row {row}): {reason}")
    if errors:
        raise ValueError("; ".join(errors))

    try:
        geographic = source.to_crs("EPSG:4326")
        for row, geometry in enumerate(geographic.geometry):
            west, south, east, north = geometry.bounds
            if (
                not np.isfinite(geometry.bounds).all()
                or south < -86 or north > 86 or west < -180 or east > 180
                or east - west > 180
            ):
                raise ValueError(
                    f"{label} source ID {ids[row]!r}: outside area measurement domain; "
                    "use 86°S–86°N and split antimeridian-crossing polygons"
                )
        projected = source.to_crs(AREA_CRS)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"{label}: cannot transform CRS for area calculation: {exc}") from exc

    for row, geometry in enumerate(projected.geometry):
        if not geometry.is_valid or not math.isfinite(geometry.area) or geometry.area <= 0:
            raise ValueError(
                f"{label} source ID {ids[row]!r}: invalid or zero-area projected polygon; "
                f"{explain_validity(geometry)}"
            )
    _attribute_names(source, selected_attributes, side)
    return AreaInput(source, projected, ids, id_field, side)


def _attribute_names(frame: gpd.GeoDataFrame, selected: dict | None, side: str) -> list[str]:
    attributes = [column for column in frame.columns if column != frame.geometry.name]
    if selected is not None:
        # Public API uses layer_a/layer_b; accept legacy a/b keys as well.
        requested = selected.get(f"layer_{side}", selected.get(side))
        if requested is not None:
            missing = set(requested) - set(attributes)
            if missing:
                raise ValueError(f"Layer {side.upper()}: unknown selected attributes: {sorted(missing)}")
            attributes = list(dict.fromkeys(requested))
    return attributes


def _overlay_frame(prepared: AreaInput, selected: dict | None) -> gpd.GeoDataFrame:
    side = prepared.side
    frame = prepared.projected
    attributes = _attribute_names(frame, selected, side)
    result = gpd.GeoDataFrame(
        {f"{side}_{column}": frame[column] for column in attributes},
        geometry=frame.geometry, crs=AREA_CRS,
    )
    result[f"src_{side}_id"] = pd.Series(prepared.ids, dtype="str")
    result[f"src_{side}_row"] = np.arange(len(frame), dtype=np.int64)
    result[f"_area_{side}"] = frame.geometry.area
    return result


def intersect_with_area(
    a: AreaInput, b: AreaInput, selected_attributes: dict | None = None,
) -> gpd.GeoDataFrame:
    """One row per A/B pair; disconnected polygon parts stay a MultiPolygon."""
    left = _overlay_frame(a, selected_attributes)
    right = _overlay_frame(b, selected_attributes)
    result = gpd.overlay(
        left, right, how="intersection", keep_geom_type=True, make_valid=False,
    )
    result["area_m2"] = result.geometry.area
    result = result.loc[result.area_m2 > 0].copy()
    result["area_ha"] = result.area_m2 / 10_000
    # All areas are measured in the same equal-area plane. Clip only numerical
    # overshoot at the bounds, not the values used in any area calculation.
    result["pct_a"] = (100 * result.area_m2 / result["_area_a"]).clip(0, 100)
    result["pct_b"] = (100 * result.area_m2 / result["_area_b"]).clip(0, 100)
    result = result.drop(columns=["_area_a", "_area_b"])
    return result.to_crs("EPSG:4326").reset_index(drop=True)
