import logging
import math
import socket
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
from ipaddress import ip_address, AddressValueError

import requests
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)

BBox = Tuple[float, float, float, float]  # (west, south, east, north) EPSG:4326

_FETCH_TIMEOUT = 10  # seconds


def _validate_url_safety(url: str) -> bool:
	"""
	Validate URL untuk SSRF protection:
	- Require http/https scheme
	- Resolve hostname dan reject private/loopback/reserved IPs
	"""
	try:
		parsed = urlparse(url)

		# Require http or https
		if parsed.scheme not in ("http", "https"):
			logger.warning(f"url_rejected: invalid_scheme {parsed.scheme}")
			return False

		# Extract hostname
		hostname = parsed.hostname
		if not hostname:
			logger.warning(f"url_rejected: no_hostname")
			return False

		# Resolve hostname
		try:
			results = socket.getaddrinfo(hostname, None)
			if not results:
				logger.warning(f"url_rejected: hostname_resolve_failed {hostname}")
				return False

			# Check first result IP
			resolved_ip = results[0][4][0]
			ip_obj = ip_address(resolved_ip)

			# Reject private, loopback, link-local, reserved, multicast
			if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_multicast:
				logger.warning(f"url_rejected: unsafe_ip {resolved_ip} for {hostname}")
				return False
		except (socket.gaierror, AddressValueError) as e:
			logger.warning(f"url_rejected: hostname_resolve_error {hostname} - {e}")
			return False

		return True
	except Exception as e:
		logger.warning(f"url_validation_error: {e}")
		return False


def _is_valid_4326_bbox(bbox: BBox) -> bool:
	"""Bbox harus dalam range WGS84 dan tidak degenerate.
	Beberapa service Esri melaporkan extent sampah (mis. xmin=-400, wkid 4326)."""
	west, south, east, north = bbox
	return (
		-180.0 <= west <= 180.0
		and -180.0 <= east <= 180.0
		and -90.0 <= south <= 90.0
		and -90.0 <= north <= 90.0
		and west < east
		and south < north
	)


def extract_bbox(layer_type: str, source_url: str, params: Optional[dict] = None) -> Optional[BBox]:
	"""
	Dispatch bbox extraction berdasarkan layer_type.
	Returns (west, south, east, north) in EPSG:4326, atau None jika gagal/invalid.
	"""
	try:
		if layer_type == "wms":
			bbox = _extract_wms_bbox(source_url, params)
		elif layer_type == "wmts":
			bbox = _extract_wmts_bbox(source_url, params)
		elif layer_type == "wfs":
			bbox = _extract_wfs_bbox(source_url, params)
		elif layer_type in ("geojson", "kml"):
			bbox = _extract_remote_vector_bbox(source_url)
		elif layer_type in ("esri_mapserver", "esri_featureserver", "esri_imageserver", "esri_tileserver", "esri_vectortileserver"):
			bbox = _extract_esri_bbox(source_url, params)
		else:
			return None

		if bbox and not _is_valid_4326_bbox(bbox):
			logger.warning(
				"bbox_out_of_range_rejected",
				extra={"layer_type": layer_type, "url": source_url, "bbox": bbox}
			)
			return None
		return bbox
	except Exception as exc:
		logger.warning(
			"bbox_extraction_failed",
			extra={"layer_type": layer_type, "url": source_url, "error": str(exc)}
		)
		return None


def _extract_wms_bbox(source_url: str, params: Optional[dict] = None) -> Optional[BBox]:
	"""Extract bbox dari WMS GetCapabilities (1.1.x dan 1.3.0)."""
	try:
		if not _validate_url_safety(source_url):
			return None

		from owslib.wms import WebMapService

		layer_name = (params or {}).get("layers") or (params or {}).get("LAYERS")
		wms = WebMapService(source_url, timeout=_FETCH_TIMEOUT)

		# Jika layer_name spesifik, cari itu dulu
		if layer_name and layer_name in wms.contents:
			layer = wms.contents[layer_name]
			bbox = layer.boundingBoxWGS84
			if bbox:
				return (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))

		# Fallback: gabung bbox dari semua layers
		all_bboxes = [v.boundingBoxWGS84 for v in wms.contents.values() if v.boundingBoxWGS84]
		if all_bboxes:
			west = min(b[0] for b in all_bboxes)
			south = min(b[1] for b in all_bboxes)
			east = max(b[2] for b in all_bboxes)
			north = max(b[3] for b in all_bboxes)
			return (west, south, east, north)
		return None
	except Exception as e:
		logger.debug(f"WMS bbox extraction failed: {e}")
		return None


def _extract_wmts_bbox(source_url: str, params: Optional[dict] = None) -> Optional[BBox]:
	"""Extract bbox dari WMTS GetCapabilities."""
	try:
		if not _validate_url_safety(source_url):
			return None

		from owslib.wmts import WebMapTileService

		layer_name = (params or {}).get("layer") or (params or {}).get("LAYER")
		wmts = WebMapTileService(source_url, timeout=_FETCH_TIMEOUT)

		# Jika layer_name spesifik, cari itu
		if layer_name and layer_name in wmts.contents:
			layer = wmts.contents[layer_name]
			bbox = layer.boundingBoxWGS84
			if bbox:
				return (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))

		# Fallback: gabung bbox dari semua layers
		all_bboxes = [v.boundingBoxWGS84 for v in wmts.contents.values() if v.boundingBoxWGS84]
		if all_bboxes:
			west = min(b[0] for b in all_bboxes)
			south = min(b[1] for b in all_bboxes)
			east = max(b[2] for b in all_bboxes)
			north = max(b[3] for b in all_bboxes)
			return (west, south, east, north)
		return None
	except Exception as e:
		logger.debug(f"WMTS bbox extraction failed: {e}")
		return None


def _extract_wfs_bbox(source_url: str, params: Optional[dict] = None) -> Optional[BBox]:
	"""Extract a WGS84 extent from WFS GetCapabilities."""
	try:
		if not _validate_url_safety(source_url):
			return None
		from owslib.wfs import WebFeatureService
		wfs = WebFeatureService(source_url, timeout=_FETCH_TIMEOUT)
		layer_name = (params or {}).get("typeName") or (params or {}).get("typename") or (params or {}).get("layers")
		if layer_name and layer_name in wfs.contents:
			bbox = wfs.contents[layer_name].boundingBoxWGS84
			if bbox:
				return tuple(float(value) for value in bbox)
		all_bboxes = [item.boundingBoxWGS84 for item in wfs.contents.values() if item.boundingBoxWGS84]
		if all_bboxes:
			return (
				min(b[0] for b in all_bboxes), min(b[1] for b in all_bboxes),
				max(b[2] for b in all_bboxes), max(b[3] for b in all_bboxes),
			)
	except Exception as exc:
		logger.debug(f"WFS bbox extraction failed: {exc}")
	return None


def _extract_remote_vector_bbox(source_url: str) -> Optional[BBox]:
	"""Read a public GeoJSON/KML URL through GeoPandas after SSRF validation."""
	try:
		if not _validate_url_safety(source_url):
			return None
		import geopandas as gpd
		gdf = gpd.read_file(source_url)
		if gdf.crs is None:
			gdf = gdf.set_crs("EPSG:4326")
		bounds = gdf.to_crs("EPSG:4326").total_bounds
		return tuple(float(value) for value in bounds)
	except Exception as exc:
		logger.debug(f"Remote vector bbox extraction failed: {exc}")
	return None


def _extract_esri_bbox(source_url: str, params: Optional[dict] = None) -> Optional[BBox]:
	"""Extract bbox dari ESRI REST service metadata."""
	try:
		if not _validate_url_safety(source_url):
			return None

		json_url = _build_esri_info_url(source_url)
		resp = requests.get(json_url, timeout=_FETCH_TIMEOUT, params={"f": "json"}, allow_redirects=False)
		resp.raise_for_status()
		data = resp.json()

		# Cari extent (prioritas: fullExtent > initialExtent > extent)
		extent = data.get("fullExtent") or data.get("initialExtent") or data.get("extent")
		if not extent:
			return None

		wkid = (extent.get("spatialReference") or {}).get("wkid", 4326)
		west = extent.get("xmin")
		south = extent.get("ymin")
		east = extent.get("xmax")
		north = extent.get("ymax")

		if any(v is None for v in [west, south, east, north]):
			return None

		west, south, east, north = float(west), float(south), float(east), float(north)

		# Reproject ke 4326 jika bukan 4326
		if wkid != 4326:
			from pyproj import Transformer
			transformer = Transformer.from_crs(f"EPSG:{wkid}", "EPSG:4326", always_xy=True)
			west, south = transformer.transform(west, south)
			east, north = transformer.transform(east, north)

		# Check for NaN values (transformation may fail silently and return NaN)
		if any(math.isnan(v) for v in [west, south, east, north]):
			logger.debug(f"ESRI bbox contains NaN after transformation: ({west}, {south}, {east}, {north})")
			return None

		return (west, south, east, north)
	except Exception as e:
		logger.debug(f"ESRI bbox extraction failed: {e}")
		return None


def _build_esri_info_url(source_url: str) -> str:
	"""
	Ambil base service URL (strip layer index jika ada).
	Contoh: .../MapServer/0 → .../MapServer
	"""
	url = source_url.rstrip("/")
	parts = url.split("/")
	if parts and parts[-1].isdigit():
		url = "/".join(parts[:-1])
	return url


def extract_bbox_from_file(path: str) -> Optional[BBox]:
	"""
	Extract bbox (west, south, east, north) in EPSG:4326 from a local file.
	Supports vector files (via geopandas) and raster files (via rasterio).
	Returns None if extraction fails.
	"""
	from pathlib import Path
	try:
		p = Path(path)
		ext = p.suffix.lower()

		VECTOR_EXTS = {'.shp', '.geojson', '.json', '.gpkg', '.kml', '.zip'}
		RASTER_EXTS = {'.tif', '.tiff', '.img', '.png', '.jpg', '.jpeg'}

		if ext in VECTOR_EXTS:
			import geopandas as gpd
			gdf = gpd.read_file(path)
			if gdf.crs is None:
				gdf = gdf.set_crs('EPSG:4326')
			gdf_4326 = gdf.to_crs('EPSG:4326')
			b = gdf_4326.total_bounds
			return (float(b[0]), float(b[1]), float(b[2]), float(b[3]))

		if ext in RASTER_EXTS:
			import rasterio
			from rasterio.crs import CRS
			from rasterio.warp import transform_bounds
			with rasterio.open(path) as src:
				crs = src.crs or CRS.from_epsg(4326)
				west, south, east, north = transform_bounds(crs, 'EPSG:4326', *src.bounds)
				west, south, east, north = float(west), float(south), float(east), float(north)
				# Check for NaN values (transformation may fail silently)
				if any(math.isnan(v) for v in [west, south, east, north]):
					logger.debug(f"Raster bbox contains NaN after transformation: ({west}, {south}, {east}, {north})")
					return None
				return (west, south, east, north)
	except Exception as e:
		logger.debug(f"File bbox extraction failed for {path}: {e}")
		return None

	return None


def get_crs_from_file(path: str) -> Optional[str]:
	"""Return CRS as EPSG string or WKT. Returns None on failure."""
	from pathlib import Path
	try:
		p = Path(path)
		ext = p.suffix.lower()

		if ext in {'.shp', '.geojson', '.json', '.gpkg', '.kml', '.zip'}:
			import geopandas as gpd
			gdf = gpd.read_file(path)
			return str(gdf.crs) if gdf.crs else None

		if ext in {'.tif', '.tiff', '.img', '.png', '.jpg', '.jpeg'}:
			import rasterio
			with rasterio.open(path) as src:
				return src.crs.to_string() if src.crs else None
	except Exception as e:
		logger.debug(f"CRS extraction failed for {path}: {e}")
		return None

	return None
