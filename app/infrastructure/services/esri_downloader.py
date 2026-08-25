"""Download all vector data from an Esri MapServer/FeatureServer service.

Runs synchronously inside the Celery worker. Supports:
- ObjectID mode (fetch all ids, query in chunks with resume)
- Pagination mode (resultOffset fallback with adaptive page split)
- Multi-format export: GeoJSON, Shapefile, GeoPackage, KMZ
- Image export for render-only MapServer services
"""

from __future__ import annotations

import json
import logging
import math
import re
import shutil
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import unquote, urlparse

from app.core.config import settings
from app.core.exceptions import DownloadCancelled, EsriDownloadError
from app.core.utils import slugify
from app.infrastructure.services.bbox_extractor import _validate_url_safety
from app.infrastructure.services.esri_client import EsriClient
from app.infrastructure.services.esri_http_utils import disable_ssl_warnings_once, timeout_tuple
from app.infrastructure.services.esri_resume_cache import ResumeCache

logger = logging.getLogger(__name__)

_TIMEOUT = (10, 120)  # connect, read
_MAX_CHUNK = 1000
_CHUNK_RETRIES = 3

# Re-export for backward compatibility with existing Celery task
from app.core.exceptions import DownloadCancelled, EsriDownloadError  # noqa: F811


@dataclass
class SublayerInfo:
    id: int
    name: str
    geometry_type: str
    max_record_count: int
    supports_geojson: bool


# ============================================================
# PUBLIC API — kept for backward compatibility with Celery task
# ============================================================

def esri_service_base(url: str) -> Optional[str]:
    """Return the .../MapServer or .../FeatureServer base, or None."""
    match = re.match(r"(.*?/(?:MapServer|FeatureServer))", url)
    return match.group(1) if match else None


def esri_sublayer_index(url: str) -> Optional[int]:
    """Sublayer index when the URL targets one sublayer (.../MapServer/3)."""
    match = re.match(r".*?/(?:MapServer|FeatureServer)/(\d+)", url)
    return int(match.group(1)) if match else None


def fetch_service_info(base_url: str) -> dict:
    """Get service metadata (kept for backward compat)."""
    if not _validate_url_safety(base_url):
        raise EsriDownloadError(f"URL failed safety validation: {base_url}")
    client = EsriClient(base_url)
    return client.get_service_info()


def list_queryable_sublayers(
    base_url: str, service_info: dict, only_id: Optional[int] = None
) -> tuple[List[SublayerInfo], List[dict]]:
    """Return (queryable sublayers, skipped entries with reason)."""
    from app.infrastructure.services.esri_client import EsriClient

    sublayers: List[SublayerInfo] = []
    skipped: List[dict] = []
    client = EsriClient(base_url)

    entries = service_info.get("layers") or []
    if not entries and service_info.get("type") == "Feature Layer":
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
            detail = client.get_layer_info(layer_id)
        except Exception as exc:
            skipped.append({"id": layer_id, "name": name, "reason": f"metadata fetch failed: {exc}"})
            continue

        layer_kind = detail.get("type") or ""
        geometry_type = detail.get("geometryType")
        if layer_kind not in ("Feature Layer", ""):
            skipped.append({"id": layer_id, "name": name, "reason": f"not a feature layer ({layer_kind})"})
            continue
        if not geometry_type:
            skipped.append({"id": layer_id, "name": name, "reason": "no geometry"})
            continue
        if not client.is_query_supported(detail):
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
    """Kept for backward compat; use EsriClient.get_object_ids() instead."""
    import requests
    from app.core.exceptions import EsriDownloadError

    resp = requests.get(f"{layer_url}/query", params={
        "where": "1=1", "returnIdsOnly": "true", "f": "json",
    }, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "error" in data:
        raise EsriDownloadError(f"Esri service error: {data['error']}")
    ids = data.get("objectIds") or []
    return sorted(ids)


# ============================================================
# EXPORT HELPERS — kept for backward compat (GeoJSON + Shapefile)
# ============================================================

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
                pts = [p for p in (geom.get("points") or []) if p is not None and all(c is not None for c in p)]
                gj_geom = {"type": "MultiPoint", "coordinates": pts}
            elif geometry_type == "esriGeometryPolyline":
                paths = [_clean_ring(p) for p in (geom.get("paths") or [])]
                gj_geom = {"type": "MultiLineString", "coordinates": [p for p in paths if len(p) >= 2]}
            elif geometry_type == "esriGeometryPolygon":
                gj_geom = _rings_to_geojson_polygon(geom.get("rings") or [])
        features.append({
            "type": "Feature",
            "geometry": gj_geom,
            "properties": feat.get("attributes") or {},
        })
    return features


def _clean_ring(ring: List) -> List:
    return [pt for pt in ring if pt is not None and all(c is not None for c in pt)]


def _ring_signed_area(ring: List[List[float]]) -> float:
    area = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _rings_to_geojson_polygon(rings: List[List[List[float]]]) -> Optional[dict]:
    if not rings:
        return None
    polygons: List[List[List[List[float]]]] = []
    holes: List[List[List[float]]] = []
    for ring in rings:
        ring = _clean_ring(ring)
        if len(ring) < 4:
            continue
        if _ring_signed_area(ring) <= 0:
            polygons.append([ring])
        else:
            holes.append(ring)
    if not polygons:
        polygons = [[ring] for ring in holes]
        holes = []
    else:
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


def _write_geojson(features: List[dict], path: Path) -> None:
    collection = {"type": "FeatureCollection", "features": features}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(collection, fh, ensure_ascii=False)


def _geom_has_none_coords(geom: Optional[dict]) -> bool:
    if not geom:
        return False
    def _check(obj) -> bool:
        if obj is None:
            return True
        if isinstance(obj, list):
            return any(_check(x) for x in obj)
        return False
    return _check(geom.get("coordinates"))


def _write_shapefile_zip(features: List[dict], shp_dir: Path, slug: str) -> Optional[str]:
    """Write features to a shapefile and zip the sidecar files."""
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    from shapely.geometry import MultiLineString, MultiPolygon

    valid = [f for f in features if f.get("geometry") and not _geom_has_none_coords(f["geometry"])]
    if not valid:
        return None

    gdf = gpd.GeoDataFrame.from_features(valid, crs="EPSG:4326")
    gdf = gdf[~gdf.geometry.isna() & ~gdf.geometry.is_empty]
    if gdf.empty:
        return None

    geom_types = set(gdf.geometry.geom_type)
    if geom_types == {"Polygon", "MultiPolygon"}:
        gdf.geometry = gdf.geometry.apply(lambda g: MultiPolygon([g]) if g.geom_type == "Polygon" else g)
    elif geom_types == {"LineString", "MultiLineString"}:
        gdf.geometry = gdf.geometry.apply(lambda g: MultiLineString([g]) if g.geom_type == "LineString" else g)

    for col in gdf.columns:
        if col == "geometry":
            continue
        if pd.api.types.is_numeric_dtype(gdf[col]):
            gdf[col] = gdf[col].fillna(np.nan)
        elif gdf[col].dtype == object:
            gdf[col] = gdf[col].fillna("")

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


# ============================================================
# EsriDownloader CLASS — full-featured orchestrator
# ============================================================

class EsriDownloader:
    """Orchestrates Esri layer download with resume cache and multi-format export.

    Usage from Celery task:
        downloader = EsriDownloader(service_url, output_formats=["geojson", "shp"])
        manifest = downloader.download_all_sublayers(dest_dir, sublayers, progress_cb=...)
    """

    def __init__(
        self,
        service_url: str,
        output_formats: Optional[List[str]] = None,
        max_workers: Optional[int] = None,
        proxy_url: str = "",
        token: str = "",
    ):
        self.service_url = service_url.rstrip("/")
        self.output_formats = output_formats or ["geojson", "shp"]
        self.max_workers = max_workers or settings.ESRI_MAX_WORKERS
        self.proxy_url = proxy_url or settings.ESRI_PROXY_URL
        self.token = token or settings.ESRI_TOKEN
        self.client = EsriClient(self.service_url, proxy_url=self.proxy_url, token=self.token)
        self.resume_cache = ResumeCache()

    # ---- control ----

    def _check_cancelled(self, progress_cb: Optional[Callable] = None) -> None:
        """Check cancel flag via progress callback state."""
        pass  # Celery cancel handled via DB flag in the task's progress callback

    # ---- chunking ----

    def get_chunk_size(self) -> int:
        return _MAX_CHUNK

    def build_chunks(self, object_ids: List[int]) -> List[List[int]]:
        chunk_size = self.get_chunk_size()
        return [object_ids[i:i + chunk_size] for i in range(0, len(object_ids), chunk_size)]

    # ---- ObjectID download ----

    def download_by_object_ids(
        self,
        layer_id: int,
        layer_name: str,
        geometry_type: str,
        dest_dir: Path,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> dict:
        """Download features using ObjectID mode with resume cache."""
        object_ids = self.client.get_object_ids(layer_id)
        target_count = len(object_ids)
        if not target_count:
            return {"id": layer_id, "name": layer_name, "feature_count": 0, "downloaded_features": 0}

        chunks = self.build_chunks(object_ids)
        total_chunks = len(chunks)
        completed = 0
        all_features: List[dict] = []
        failed_chunks: List[tuple] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for start in range(0, total_chunks, self.max_workers):
                window = chunks[start:start + self.max_workers]
                future_map = {
                    executor.submit(self._fetch_chunk_with_resume, layer_id, chunk, geometry_type): chunk
                    for chunk in window
                }

                for future in as_completed(future_map):
                    chunk = future_map[future]
                    try:
                        features = future.result()
                        all_features.extend(features)
                    except Exception as error:
                        failed_chunks.append((chunk, str(error)))
                        logger.error("Chunk failed for layer %s: %s", layer_id, error)

                    completed += 1
                    if progress_cb:
                        progress_cb(min(start + completed * self.max_workers, target_count), target_count)

        if failed_chunks:
            raise EsriDownloadError(
                f"{len(failed_chunks)} ObjectID batch(es) failed. Download would be incomplete."
            )

        if len(all_features) < target_count:
            raise EsriDownloadError(
                f"Incomplete ObjectID download: {len(all_features)}/{target_count} features."
            )

        return self._export_and_save(layer_id, layer_name, geometry_type, all_features, dest_dir)

    def _fetch_chunk_with_resume(
        self, layer_id: int, chunk: List[int], geometry_type: str
    ) -> List[dict]:
        """Fetch one ObjectID chunk, using resume cache if available."""
        cache_path = self.resume_cache.objectid_chunk_path(
            self.service_url, layer_id, chunk
        )
        cached = self.resume_cache.read_features(
            cache_path, service_url=self.service_url, geometry_type=geometry_type,
        )
        if cached is not None:
            logger.debug("Resume cache hit for layer %s chunk %s", layer_id, chunk[:3])
            return cached

        features = self.client.fetch_features_adaptive(layer_id, chunk)
        self.resume_cache.write_features(
            cache_path,
            service_url=self.service_url,
            layer_id=layer_id,
            mode="object_ids",
            features=features,
            geometry_type=geometry_type,
            meta={"chunk_size": len(chunk), "first_id": chunk[0], "last_id": chunk[-1]},
        )
        return features

    # ---- Pagination download ----

    def download_by_pagination(
        self,
        layer_id: int,
        layer_name: str,
        geometry_type: str,
        dest_dir: Path,
        page_size: Optional[int] = None,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> dict:
        """Download features using resultOffset pagination with adaptive page split."""
        page_size = page_size or self.get_chunk_size()

        # Try to get total count
        try:
            target_count = self.client.get_feature_count(layer_id)
        except Exception:
            target_count = 0

        offset = 0
        all_features: List[dict] = []
        completed = 0
        total_pages = max(1, math.ceil(target_count / page_size)) if target_count else 0

        while True:
            features = self._fetch_page_adaptive(
                layer_id, offset=offset, page_size=page_size,
                geometry_type=geometry_type, min_page_size=1,
            )
            if not features:
                break

            all_features.extend(features)
            completed += 1
            offset += page_size

            if progress_cb:
                progress_cb(min(offset, target_count), target_count if target_count else completed)

            if target_count and len(all_features) >= target_count:
                break
            if len(features) < page_size:
                break

        if target_count and len(all_features) < target_count:
            raise EsriDownloadError(
                f"Incomplete pagination download: {len(all_features)}/{target_count} features."
            )

        return self._export_and_save(layer_id, layer_name, geometry_type, all_features, dest_dir)

    def _fetch_page_adaptive(
        self, layer_id: int, offset: int, page_size: int,
        geometry_type: str, min_page_size: int = 1,
    ) -> List[dict]:
        """Fetch a page with adaptive split on failure."""
        try:
            return self._fetch_page_with_resume(layer_id, offset, page_size, geometry_type)
        except Exception as exc:
            if page_size <= min_page_size:
                raise EsriDownloadError(f"Page {offset} failed: {exc}") from exc
            left_size = max(min_page_size, page_size // 2)
            right_size = page_size - left_size
            features = []
            features.extend(self._fetch_page_adaptive(
                layer_id, offset=offset, page_size=left_size,
                geometry_type=geometry_type, min_page_size=min_page_size,
            ))
            if right_size > 0:
                features.extend(self._fetch_page_adaptive(
                    layer_id, offset=offset + left_size, page_size=right_size,
                    geometry_type=geometry_type, min_page_size=min_page_size,
                ))
            return features

    def _fetch_page_with_resume(
        self, layer_id: int, offset: int, page_size: int, geometry_type: str
    ) -> List[dict]:
        """Fetch a pagination page with resume cache."""
        cache_path = self.resume_cache.page_path(
            self.service_url, layer_id, offset, page_size,
        )
        cached = self.resume_cache.read_features(
            cache_path, service_url=self.service_url, geometry_type=geometry_type,
        )
        if cached is not None:
            logger.debug("Resume cache hit for layer %s page offset=%s", layer_id, offset)
            return cached

        features = self.client.fetch_features_page(layer_id, offset=offset, page_size=page_size)
        self.resume_cache.write_features(
            cache_path,
            service_url=self.service_url,
            layer_id=layer_id,
            mode="pagination",
            features=features,
            geometry_type=geometry_type,
            meta={"offset": offset, "page_size": page_size},
        )
        return features

    # ---- Export & Save ----

    def _export_and_save(
        self,
        layer_id: int,
        layer_name: str,
        geometry_type: str,
        features: List[dict],
        dest_dir: Path,
    ) -> dict:
        """Export features to all requested formats and save to dest_dir."""
        slug = slugify(layer_name) or f"layer_{layer_id}"
        out_dir = dest_dir / f"{layer_id}_{slug}"
        out_dir.mkdir(parents=True, exist_ok=True)

        result = {
            "id": layer_id,
            "name": layer_name,
            "geometry_type": geometry_type,
            "feature_count": len(features),
            "downloaded_features": len(features),
        }

        geojson_collection = {"type": "FeatureCollection", "features": features}

        for fmt in self.output_formats:
            fmt_lower = fmt.lower()
            if fmt_lower in ("geojson", "json"):
                geojson_path = out_dir / f"{slug}.geojson"
                _write_geojson(features, geojson_path)
                result["geojson"] = str(geojson_path)

            elif fmt_lower in ("shp", "shapefile", "shp_zip"):
                zip_path = _write_shapefile_zip(features, out_dir / "_shp_tmp", slug)
                if zip_path:
                    result["shapefile_zip"] = zip_path

            elif fmt_lower in ("gpkg", "geopackage"):
                gpkg_path = _write_geopackage(features, out_dir, slug, geometry_type)
                if gpkg_path:
                    result["geopackage"] = gpkg_path

            elif fmt_lower in ("kmz", "kml"):
                kmz_path = _write_kmz(features, out_dir, slug, geometry_type)
                if kmz_path:
                    result["kmz"] = kmz_path

        return result

    # ---- Image export (render-only MapServer) ----

    def download_map_image(
        self,
        layer_info: dict,
        dest_dir: Path,
        layer_name: str = "Map Image",
        image_format: str = "PNG32",
        status_cb: Optional[Callable[[str], None]] = None,
    ) -> dict:
        """Export a render-only MapServer as a georeferenced image + world file."""
        # Determine extent
        extent = self._select_image_extent(layer_info)
        if not extent:
            raise EsriDownloadError("Image export extent unavailable or contains NaN")

        max_w = int(layer_info.get("maxImageWidth") or 4096)
        max_h = int(layer_info.get("maxImageHeight") or 4096)

        extent_w = max(float(extent["xmax"]) - float(extent["xmin"]), 1e-9)
        extent_h = max(float(extent["ymax"]) - float(extent["ymin"]), 1e-9)
        aspect = extent_w / extent_h
        width = min(max_w, 4096)
        height = max(256, int(round(width / aspect)))
        if height > max_h:
            height = min(max_h, 4096)
            width = max(256, int(round(height * aspect)))
        width = max(256, min(width, max_w))
        height = max(256, min(height, max_h))

        ext = {"PNG32": ".png", "PNG24": ".png", "PNG": ".png", "JPG": ".jpg", "JPEG": ".jpg", "TIFF": ".tif", "TIF": ".tif"}.get(image_format.upper(), ".png")
        output_name = slugify(layer_name) or "map_image"
        output_path = dest_dir / f"{output_name}{ext}"

        if status_cb:
            status_cb(f"Export map image: {layer_name}")

        # Build export URL via EsriClient's session
        params = {
            "bbox": f"{extent['xmin']},{extent['ymin']},{extent['xmax']},{extent['ymax']}",
            "bboxSR": (extent.get("spatialReference") or {}).get("latestWkid") or (extent.get("spatialReference") or {}).get("wkid") or 4326,
            "imageSR": (extent.get("spatialReference") or {}).get("latestWkid") or (extent.get("spatialReference") or {}).get("wkid") or 4326,
            "size": f"{width},{height}",
            "format": image_format,
            "transparent": "true",
            "dpi": "96",
            "f": "image",
        }
        url = self.client._build_url(f"{self.service_url}/export", params)
        resp = self.client.session.get(
            url, timeout=timeout_tuple(180), allow_redirects=True,
            verify=self.client._request_verify(),
        )
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "json" in content_type.lower() or resp.content[:1] in (b"{", b"["):
            raise EsriDownloadError(f"Image export failed: {resp.text[:500]}")

        output_path.write_bytes(resp.content)
        world_path = self._write_world_file(output_path, extent, width, height)

        metadata = {
            "download_mode": "image_export",
            "source_url": self.service_url,
            "export_url": f"{self.service_url}/export",
            "format": image_format,
            "width": width,
            "height": height,
            "extent": extent,
            "world_file": str(world_path),
        }
        metadata_path = str(output_path.with_suffix(".metadata.json"))
        Path(metadata_path).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "id": "__map_image__",
            "name": layer_name,
            "image": str(output_path),
            "world_file": str(world_path),
            "metadata": metadata_path,
        }

    @staticmethod
    def _clean_extent_value(value) -> Optional[float]:
        try:
            if isinstance(value, str) and value.lower() == "nan":
                return None
            number = float(value)
            if math.isnan(number) or math.isinf(number):
                return None
            return number
        except Exception:
            return None

    def _select_image_extent(self, info: dict) -> Optional[dict]:
        def valid_extent(extent):
            if not isinstance(extent, dict):
                return None
            xmin = self._clean_extent_value(extent.get("xmin"))
            ymin = self._clean_extent_value(extent.get("ymin"))
            xmax = self._clean_extent_value(extent.get("xmax"))
            ymax = self._clean_extent_value(extent.get("ymax"))
            if None in (xmin, ymin, xmax, ymax) or xmin == xmax or ymin == ymax:
                return None
            return {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax, "spatialReference": extent.get("spatialReference") or {}}
        return valid_extent(info.get("fullExtent")) or valid_extent(info.get("initialExtent"))

    @staticmethod
    def _write_world_file(image_path: Path, extent: dict, width: int, height: int) -> Path:
        ext = image_path.suffix.lower()
        world_ext = {".png": ".pgw", ".jpg": ".jgw", ".jpeg": ".jgw", ".tif": ".tfw", ".tiff": ".tfw"}.get(ext, ".wld")
        world_path = image_path.with_suffix(world_ext)
        xmin, ymin, xmax, ymax = extent["xmin"], extent["ymin"], extent["xmax"], extent["ymax"]
        pixel_x = (xmax - xmin) / float(width)
        pixel_y = -abs((ymax - ymin) / float(height))
        center_x = xmin + pixel_x / 2.0
        center_y = ymax + pixel_y / 2.0
        world_path.write_text("\n".join([str(pixel_x), "0.0", "0.0", str(pixel_y), str(center_x), str(center_y)]) + "\n", encoding="utf-8")
        return world_path

    # ---- Full service download ----

    def download_all_sublayers(
        self,
        dest_dir: Path,
        sublayers: List[SublayerInfo],
        render_only_info: Optional[dict] = None,
        progress_cb: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """Download every sublayer + optional render-only image.

        progress_cb receives {"sublayers_done", "sublayers_total", "current_sublayer",
        "features_done", "features_total"} and may raise DownloadCancelled to abort.
        """
        if dest_dir.exists():
            shutil.rmtree(dest_dir, ignore_errors=True)
        dest_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "service_url": self.service_url,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "sublayers": [],
            "skipped": [],
        }

        total_subs = len(sublayers)

        # Handle render-only MapServer
        if render_only_info:
            try:
                entry = self.download_map_image(
                    render_only_info, dest_dir,
                    layer_name=render_only_info.get("name", "Map Image"),
                )
                manifest["sublayers"].append(entry)
            except Exception as exc:
                logger.error("Render-only image export failed: %s", exc)
                manifest["sublayers"].append({"id": "__map_image__", "error": str(exc)})

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
                # Try ObjectID mode first, fallback to pagination
                entry = self.download_by_object_ids(
                    sub.id, sub.name, sub.geometry_type, dest_dir, progress_cb=_sub_progress,
                )
            except EsriDownloadError as exc:
                logger.warning(
                    "ObjectID download failed for layer %s (%s); using pagination fallback: %s",
                    sub.id, sub.name, exc,
                )
                try:
                    entry = self.download_by_pagination(
                        sub.id, sub.name, sub.geometry_type, dest_dir, progress_cb=_sub_progress,
                    )
                except EsriDownloadError as exc2:
                    logger.error("Both ObjectID and pagination failed for layer %s: %s", sub.id, exc2)
                    entry = {"id": sub.id, "name": sub.name, "error": str(exc2)}

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


# ============================================================
# STANDALONE EXPORTERS — GeoPackage & KMZ (Phase 3 prep)
# ponytail: in one file, not mixin-per-format
# ============================================================

def _write_geopackage(
    features: List[dict], dest_dir: Path, slug: str, geometry_type: str
) -> Optional[str]:
    """Write features to a GeoPackage file using geopandas."""
    import geopandas as gpd

    valid = [f for f in features if f.get("geometry") and not _geom_has_none_coords(f["geometry"])]
    if not valid:
        return None

    gdf = gpd.GeoDataFrame.from_features(valid, crs="EPSG:4326")
    gdf = gdf[~gdf.geometry.isna() & ~gdf.geometry.is_empty]
    if gdf.empty:
        return None

    gpkg_path = dest_dir / f"{slug}.gpkg"
    # Normalize mixed geometry types (same as Shapefile handler)
    from shapely.geometry import MultiLineString, MultiPolygon
    geom_types = set(gdf.geometry.geom_type)
    if geom_types == {"Polygon", "MultiPolygon"}:
        gdf.geometry = gdf.geometry.apply(lambda g: MultiPolygon([g]) if g.geom_type == "Polygon" else g)
    elif geom_types == {"LineString", "MultiLineString"}:
        gdf.geometry = gdf.geometry.apply(lambda g: MultiLineString([g]) if g.geom_type == "LineString" else g)

    gdf.to_file(str(gpkg_path), driver="GPKG")
    return str(gpkg_path)





def _write_kmz(
    features: List[dict], dest_dir: Path, slug: str, geometry_type: str
) -> Optional[str]:
    """Write features to a KMZ file (zipped KML)."""
    valid = [f for f in features if f.get("geometry") and not _geom_has_none_coords(f["geometry"])]
    if not valid:
        return None

    kmz_path = dest_dir / f"{slug}.kmz"
    with zipfile.ZipFile(kmz_path, "w", zipfile.ZIP_DEFLATED) as zf:
        kml_content = _features_to_kml(valid, slug, geometry_type)
        zf.writestr(f"{slug}.kml", kml_content.encode("utf-8"))

    return str(kmz_path)


def _features_to_kml(features: List[dict], name: str, geometry_type: str) -> str:
    """Convert GeoJSON features to KML string."""
    from xml.sax.saxutils import escape

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '<Document>',
        f'<name>{escape(name)}</name>',
    ]

    for feat in features:
        geom = feat.get("geometry")
        props = feat.get("properties", {})
        if not geom:
            continue

        parts.append('<Placemark>')
        if props.get("name"):
            parts.append(f'<name>{escape(str(props["name"]))}</name>')

        # ExtendedData for properties
        parts.append('<ExtendedData>')
        for key, val in props.items():
            if val is not None:
                parts.append(f'<Data name="{escape(str(key))}"><value>{escape(str(val))}</value></Data>')
        parts.append('</ExtendedData>')

        gtype = geom.get("type", "")
        coords = geom.get("coordinates")

        if gtype == "Point" and len(coords) >= 2:
            parts.append(f'<Point><coordinates>{coords[0]},{coords[1]},0</coordinates></Point>')
        elif gtype in ("LineString", "MultiLineString"):
            coord_strs = []
            if gtype == "LineString":
                coord_strs = [f"{c[0]},{c[1]},0" for c in coords if len(c) >= 2]
            else:
                for line in coords:
                    coord_strs.extend(f"{c[0]},{c[1]},0" for c in line if len(c) >= 2)
            if coord_strs:
                parts.append(f'<LineString><coordinates>{" ".join(coord_strs)}</coordinates></LineString>')
        elif gtype in ("Polygon", "MultiPolygon"):
            coord_strs = []
            if gtype == "Polygon":
                for ring in coords:
                    coord_strs.extend(f"{c[0]},{c[1]},0" for c in ring if len(c) >= 2)
            else:
                for poly in coords:
                    for ring in poly:
                        coord_strs.extend(f"{c[0]},{c[1]},0" for c in ring if len(c) >= 2)
            if coord_strs:
                parts.append(f'<Polygon><outerBoundaryIs><LinearRing><coordinates>{" ".join(coord_strs)}</coordinates></LinearRing></outerBoundaryIs></Polygon>')

        parts.append('</Placemark>')

    parts.extend(['</Document>', '</kml>'])
    return "\n".join(parts)


# ============================================================
# BACKWARD-COMPAT module-level functions (used by existing task)
# ============================================================

def download_sublayer(
    base_url: str,
    sub: SublayerInfo,
    dest_dir: Path,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """Backward compat: download one sublayer using EsriDownloader."""
    downloader = EsriDownloader(base_url)
    return downloader.download_by_object_ids(
        sub.id, sub.name, sub.geometry_type, dest_dir, progress_cb=progress_cb,
    )


def download_service(
    service_url: str,
    dest_dir: Path,
    progress_cb: Optional[Callable[[dict], None]] = None,
    output_formats: Optional[List[str]] = None,
    proxy_url: str = "",
    token: str = "",
) -> dict:
    """Backward compat: download all sublayers using EsriDownloader."""
    base_url = esri_service_base(service_url)
    if not base_url:
        raise EsriDownloadError(f"Not a MapServer/FeatureServer URL: {service_url}")

    only_id = esri_sublayer_index(service_url)
    client = EsriClient(base_url, proxy_url=proxy_url, token=token)
    service_info = client.get_service_info()
    sublayers, skipped = list_queryable_sublayers(base_url, service_info, only_id=only_id)

    if not sublayers:
        # Check for render-only MapServer
        if client.is_render_only_service(service_info):
            render_info = client.build_render_only_layer(service_info)
            downloader = EsriDownloader(base_url, output_formats=output_formats, proxy_url=proxy_url, token=token)
            dest_dir.mkdir(parents=True, exist_ok=True)
            entry = downloader.download_map_image(render_info, dest_dir, render_info.get("name", "Map Image"))
            manifest = {
                "service_url": base_url,
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "sublayers": [entry],
                "skipped": skipped,
            }
            with open(dest_dir / "manifest.json", "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, ensure_ascii=False, indent=2)
            return manifest
        raise EsriDownloadError("No queryable feature sublayers found in service")

    downloader = EsriDownloader(base_url, output_formats=output_formats, proxy_url=proxy_url, token=token)
    return downloader.download_all_sublayers(dest_dir, sublayers, progress_cb=progress_cb)
