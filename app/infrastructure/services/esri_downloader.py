"""Download all vector data from an Esri MapServer/FeatureServer service.

Runs synchronously inside the Celery worker. Each queryable sublayer is
exported as GeoJSON + zipped Shapefile under the destination directory.
Pagination uses the objectIds strategy (fetch all ids, query in chunks)
so it also works on old servers without resultOffset support.
"""

import json
import logging
import re
import shutil
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

import requests

from app.core.utils import slugify
from app.infrastructure.services.bbox_extractor import _validate_url_safety

logger = logging.getLogger(__name__)

_TIMEOUT = (10, 120)  # connect, read
_MAX_CHUNK = 1000
_CHUNK_RETRIES = 3

RequestsError = requests.exceptions.RequestException


class EsriDownloadError(Exception):
    """Raised when the remote Esri service cannot be downloaded."""


class DownloadCancelled(Exception):
    """Raised by progress callbacks to abort a cancelled download."""


@dataclass
class SublayerInfo:
    id: int
    name: str
    geometry_type: str
    max_record_count: int
    supports_geojson: bool


def esri_service_base(url: str) -> Optional[str]:
    """Return the .../MapServer or .../FeatureServer base, or None.

    Also returns the sublayer index if the URL points at a single sublayer
    (e.g. .../MapServer/3) — as a tuple is awkward for callers that only
    need the base, the index is exposed via esri_sublayer_index().
    """
    match = re.match(r"(.*?/(?:MapServer|FeatureServer))", url)
    return match.group(1) if match else None


def esri_sublayer_index(url: str) -> Optional[int]:
    """Sublayer index when the URL targets one sublayer (.../MapServer/3)."""
    match = re.match(r".*?/(?:MapServer|FeatureServer)/(\d+)", url)
    return int(match.group(1)) if match else None


def _get_json(url: str, params: dict) -> dict:
    resp = requests.get(url, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "error" in data:
        raise EsriDownloadError(f"Esri service error from {url}: {data['error']}")
    return data


def fetch_service_info(base_url: str) -> dict:
    if not _validate_url_safety(base_url):
        raise EsriDownloadError(f"URL failed safety validation: {base_url}")
    return _get_json(base_url, {"f": "json"})


def list_queryable_sublayers(
    base_url: str, service_info: dict, only_id: Optional[int] = None
) -> tuple[List[SublayerInfo], List[dict]]:
    """Return (queryable sublayers, skipped entries with reason)."""
    sublayers: List[SublayerInfo] = []
    skipped: List[dict] = []

    entries = service_info.get("layers") or []
    if not entries and service_info.get("type") == "Feature Layer":
        # base_url itself is a single layer endpoint
        entries = [{"id": service_info.get("id", 0), "name": service_info.get("name", "layer")}]

    for entry in entries:
        layer_id = entry.get("id")
        name = entry.get("name") or f"layer_{layer_id}"
        if only_id is not None and layer_id != only_id:
            continue
        if entry.get("subLayerIds"):
            skipped.append({"id": layer_id, "name": name, "reason": "group layer"})
            continue

        try:
            detail = _get_json(f"{base_url}/{layer_id}", {"f": "json"})
        except (RequestsError, EsriDownloadError) as exc:
            skipped.append({"id": layer_id, "name": name, "reason": f"metadata fetch failed: {exc}"})
            continue

        layer_kind = detail.get("type") or ""
        geometry_type = detail.get("geometryType")
        capabilities = detail.get("capabilities") or ""
        if layer_kind not in ("Feature Layer", ""):
            skipped.append({"id": layer_id, "name": name, "reason": f"not a feature layer ({layer_kind})"})
            continue
        if not geometry_type:
            skipped.append({"id": layer_id, "name": name, "reason": "no geometry"})
            continue
        if capabilities and "Query" not in capabilities:
            skipped.append({"id": layer_id, "name": name, "reason": "query not supported"})
            continue

        sublayers.append(SublayerInfo(
            id=layer_id,
            name=name,
            geometry_type=geometry_type,
            max_record_count=int(detail.get("maxRecordCount") or _MAX_CHUNK),
            supports_geojson="geojson" in (detail.get("supportedQueryFormats") or "").lower(),
        ))

    return sublayers, skipped


def fetch_object_ids(layer_url: str) -> List[int]:
    data = _get_json(f"{layer_url}/query", {
        "where": "1=1",
        "returnIdsOnly": "true",
        "f": "json",
    })
    ids = data.get("objectIds") or []
    return sorted(ids)


def esri_json_to_geojson_features(data: dict) -> List[dict]:
    """Convert an Esri JSON featureSet to GeoJSON features."""
    geometry_type = data.get("geometryType") or ""
    features = []
    for feat in data.get("features") or []:
        geom = feat.get("geometry")
        gj_geom = None
        if geom:
            if geometry_type == "esriGeometryPoint" and geom.get("x") is not None:
                gj_geom = {"type": "Point", "coordinates": [geom["x"], geom["y"]]}
            elif geometry_type == "esriGeometryMultipoint":
                gj_geom = {"type": "MultiPoint", "coordinates": geom.get("points") or []}
            elif geometry_type == "esriGeometryPolyline":
                gj_geom = {"type": "MultiLineString", "coordinates": geom.get("paths") or []}
            elif geometry_type == "esriGeometryPolygon":
                gj_geom = _rings_to_geojson_polygon(geom.get("rings") or [])
        features.append({
            "type": "Feature",
            "geometry": gj_geom,
            "properties": feat.get("attributes") or {},
        })
    return features


def _ring_signed_area(ring: List[List[float]]) -> float:
    area = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        area += x1 * y2 - x2 * y1
    return area / 2.0

def _rings_to_geojson_polygon(rings: List[List[List[float]]]) -> Optional[dict]:
    """Esri rings → Polygon/MultiPolygon. Esri: exterior rings are clockwise
    (negative signed area), holes counter-clockwise."""
    if not rings:
        return None
    polygons: List[List[List[List[float]]]] = []
    holes: List[List[List[float]]] = []
    for ring in rings:
        if len(ring) < 4:
            continue
        if _ring_signed_area(ring) <= 0:
            polygons.append([ring])
        else:
            holes.append(ring)
    if not polygons:
        # all rings counter-clockwise (non-spec server) — treat each as exterior
        polygons = [[ring] for ring in holes]
        holes = []
    else:
        # naive hole assignment: attach to first polygon containing its first point
        from shapely.geometry import Point, Polygon as ShpPolygon
        for hole in holes:
            pt = Point(hole[0][0], hole[0][1])
            for poly in polygons:
                if ShpPolygon(poly[0]).contains(pt):
                    poly.append(hole)
                    break
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def fetch_chunk(layer_url: str, object_ids: List[int], use_geojson: bool) -> tuple[List[dict], bool]:
    """Fetch one chunk of features. Returns (features, use_geojson) — the flag
    flips to False permanently if the server rejects f=geojson."""
    params = {
        "objectIds": ",".join(str(i) for i in object_ids),
        "outFields": "*",
        "outSR": "4326",
        "returnGeometry": "true",
        "where": "1=1",
        "f": "geojson" if use_geojson else "json",
    }

    last_exc: Optional[Exception] = None
    for attempt in range(1, _CHUNK_RETRIES + 1):
        try:
            # POST avoids URL length limits with up to 1000 ids
            resp = requests.post(f"{layer_url}/query", data=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, dict) and "error" in data:
                if use_geojson:
                    return fetch_chunk(layer_url, object_ids, use_geojson=False)
                raise EsriDownloadError(f"Esri query error: {data['error']}")

            if data.get("exceededTransferLimit") and len(object_ids) > 1:
                mid = len(object_ids) // 2
                first, flag = fetch_chunk(layer_url, object_ids[:mid], use_geojson)
                second, flag = fetch_chunk(layer_url, object_ids[mid:], flag)
                return first + second, flag

            if use_geojson:
                return data.get("features") or [], True
            return esri_json_to_geojson_features(data), False
        except (RequestsError, ValueError) as exc:
            last_exc = exc
            logger.warning("Chunk fetch attempt %s/%s failed for %s: %s",
                           attempt, _CHUNK_RETRIES, layer_url, exc)
            time.sleep(2 * attempt)

    raise EsriDownloadError(f"Chunk download failed after {_CHUNK_RETRIES} attempts: {last_exc}")


def _write_geojson(features: List[dict], path: Path) -> None:
    collection = {"type": "FeatureCollection", "features": features}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(collection, fh, ensure_ascii=False)


def _write_shapefile_zip(features: List[dict], shp_dir: Path, slug: str) -> Optional[str]:
    """Write features to a shapefile and zip the sidecar files. Returns the
    zip path or None when no valid geometries exist."""
    import geopandas as gpd

    valid = [f for f in features if f.get("geometry")]
    if not valid:
        return None

    gdf = gpd.GeoDataFrame.from_features(valid, crs="EPSG:4326")
    gdf = gdf[~gdf.geometry.isna() & ~gdf.geometry.is_empty]
    if gdf.empty:
        return None

    # Shapefile cannot mix Polygon/MultiPolygon (or Line/MultiLine) in one file
    from shapely.geometry import MultiLineString, MultiPolygon
    geom_types = set(gdf.geometry.geom_type)
    if geom_types == {"Polygon", "MultiPolygon"}:
        gdf.geometry = gdf.geometry.apply(
            lambda g: MultiPolygon([g]) if g.geom_type == "Polygon" else g)
    elif geom_types == {"LineString", "MultiLineString"}:
        gdf.geometry = gdf.geometry.apply(
            lambda g: MultiLineString([g]) if g.geom_type == "LineString" else g)

    shp_dir.mkdir(parents=True, exist_ok=True)
    shp_path = shp_dir / f"{slug}.shp"
    gdf.to_file(shp_path, driver="ESRI Shapefile")

    zip_path = shp_dir.parent / f"{slug}_shp.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for sidecar in sorted(shp_dir.iterdir()):
            if sidecar.is_file():
                zf.write(sidecar, sidecar.name)
    shutil.rmtree(shp_dir, ignore_errors=True)
    return str(zip_path)


def download_sublayer(
    base_url: str,
    sub: SublayerInfo,
    dest_dir: Path,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> dict:
    layer_url = f"{base_url}/{sub.id}"
    result = {"id": sub.id, "name": sub.name, "geometry_type": sub.geometry_type}

    object_ids = fetch_object_ids(layer_url)
    total = len(object_ids)
    result["feature_count"] = total
    if not total:
        return result

    chunk_size = min(sub.max_record_count or _MAX_CHUNK, _MAX_CHUNK)
    use_geojson = sub.supports_geojson
    features: List[dict] = []
    for start in range(0, total, chunk_size):
        chunk_ids = object_ids[start:start + chunk_size]
        chunk_features, use_geojson = fetch_chunk(layer_url, chunk_ids, use_geojson)
        features.extend(chunk_features)
        if progress_cb:
            progress_cb(min(start + chunk_size, total), total)

    slug = slugify(sub.name) or f"layer_{sub.id}"
    out_dir = dest_dir / f"{sub.id}_{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)

    geojson_path = out_dir / f"{slug}.geojson"
    _write_geojson(features, geojson_path)
    result["geojson"] = str(geojson_path)

    zip_path = _write_shapefile_zip(features, out_dir / "_shp_tmp", slug)
    if zip_path:
        # _write_shapefile_zip writes the zip next to the tmp dir (inside out_dir)
        result["shapefile_zip"] = zip_path
    result["downloaded_features"] = len(features)
    return result


def download_service(
    service_url: str,
    dest_dir: Path,
    progress_cb: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Download every queryable sublayer of an Esri service into dest_dir.

    progress_cb receives {"sublayers_done", "sublayers_total", "current_sublayer",
    "features_done", "features_total"} and may raise DownloadCancelled to abort.
    """
    base_url = esri_service_base(service_url)
    if not base_url:
        raise EsriDownloadError(f"Not a MapServer/FeatureServer URL: {service_url}")

    only_id = esri_sublayer_index(service_url)
    service_info = fetch_service_info(base_url)
    sublayers, skipped = list_queryable_sublayers(base_url, service_info, only_id=only_id)
    if not sublayers:
        raise EsriDownloadError("No queryable feature sublayers found in service")

    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "service_url": base_url,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "sublayers": [],
        "skipped": skipped,
    }

    total_subs = len(sublayers)
    for index, sub in enumerate(sublayers):
        def _sub_progress(done: int, total: int, _sub=sub, _index=index):
            if progress_cb:
                progress_cb({
                    "sublayers_done": _index,
                    "sublayers_total": total_subs,
                    "current_sublayer": _sub.name,
                    "features_done": done,
                    "features_total": total,
                })

        try:
            entry = download_sublayer(base_url, sub, dest_dir, _sub_progress)
        except EsriDownloadError as exc:
            entry = {"id": sub.id, "name": sub.name, "error": str(exc)}
            logger.error("Sublayer %s (%s) failed: %s", sub.id, sub.name, exc)
        manifest["sublayers"].append(entry)

        if progress_cb:
            progress_cb({
                "sublayers_done": index + 1,
                "sublayers_total": total_subs,
                "current_sublayer": sub.name,
                "features_done": entry.get("downloaded_features", 0),
                "features_total": entry.get("feature_count", 0),
            })

    with open(dest_dir / "manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    return manifest
