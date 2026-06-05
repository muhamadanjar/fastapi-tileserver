import logging
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


def extract_bbox(layer_type: str, source_url: str, params: Optional[dict] = None) -> Optional[BBox]:
	"""
	Dispatch bbox extraction berdasarkan layer_type.
	Returns (west, south, east, north) in EPSG:4326, atau None jika gagal.
	"""
	try:
		if layer_type == "wms":
			return _extract_wms_bbox(source_url, params)
		elif layer_type == "wmts":
			return _extract_wmts_bbox(source_url, params)
		elif layer_type in ("esri_mapserver", "esri_featureserver", "esri_imageserver", "esri_tileserver", "esri_vectortileserver"):
			return _extract_esri_bbox(source_url, params)
		else:
			return None
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
