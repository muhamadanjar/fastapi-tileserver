"""ArcGIS REST client for Esri MapServer/FeatureServer services.

Ported from rest_service_downloader/core/arcgis_client.py, adapted for
server-side use: supports proxy URL rewriting, token injection, SSL ignore,
POST fallback, Celery-friendly (no threading cancel_checker).
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode, quote

import requests

from app.core.exceptions import EsriDownloadError, ServiceConnectionError
from app.core.config import settings
from app.infrastructure.services.esri_http_utils import (
    create_retry_session,
    disable_ssl_warnings_once,
    timeout_tuple,
)

REQUEST_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 180
MAX_SAFE_GET_URL_LENGTH = 1800

logger = logging.getLogger(__name__)


def _validate_proxy_url(url: str) -> str:
    """Basic proxy URL validation — must be http/https and end with ? or /."""
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Proxy URL must start with http:// or https://, got: {url}")
    return url.rstrip("&")


class EsriClient:
    """Client for ArcGIS REST services (MapServer/FeatureServer).

    Handles: JSON requests, GeoJSON↔EsriJSON conversion, POST fallback,
    layer discovery, geometry inference, query capability detection,
    proxy URL rewriting, and token injection.
    """

    def __init__(
        self,
        service_url: str,
        proxy_url: str = "",
        token: str = "",
    ):
        self.service_url = service_url.rstrip("/")
        self.proxy_url = _validate_proxy_url(proxy_url)
        self.token = token.strip()
        self.use_proxy = bool(self.proxy_url)
        self.use_token = bool(self.token)
        self.session = create_retry_session(
            headers={
                "User-Agent": "Mozilla/5.0",
            },
            retry_post=True,
        )
        if self.use_proxy:
            logger.debug("EsriClient proxy enabled: %s", self.proxy_url[:50] + "...")
        if self.use_token:
            logger.debug("EsriClient token enabled")

    def _request_verify(self) -> bool:
        verify = not settings.ESRI_IGNORE_SSL
        if not verify:
            disable_ssl_warnings_once(service_url=self.service_url)
        return verify

    @staticmethod
    def _looks_like_html(text: str) -> bool:
        sample = str(text or "").lstrip()[:500].lower()
        return (
            sample.startswith("<!doctype html")
            or sample.startswith("<html")
            or "<html" in sample
        )

    # =================================================
    # REQUEST HELPERS
    # =================================================

    def build_final_url(self, url: str, params: dict | None = None) -> str:
        """Build request URL with optional proxy rewriting and token injection.

        When proxy is enabled:
            target = https://esri.server/MapServer/0/query?where=1=1
            proxy =  https://proxy.example.com/api/proxy?
            result = https://proxy.example.com/api/proxy?https%3A%2F%2Fesri.server%2F...

        When proxy is disabled, returns target URL with query params.
        Token is appended as a query param when use_token is True.
        """
        params = params or {}
        if self.use_token and self.token:
            params["token"] = self.token

        query = urlencode(params)
        target_url = f"{url}?{query}" if query else url

        if self.use_proxy:
            proxy = self.proxy_url
            if not proxy.endswith("?"):
                proxy += "?"
            return proxy + quote(target_url, safe="")

        return target_url

    def _build_url(self, url: str, params: dict | None = None) -> str:
        """Alias for build_final_url for internal use."""
        return self.build_final_url(url, params)

    def get_json(
        self, url: str, params: dict | None = None, timeout: int = REQUEST_TIMEOUT
    ) -> dict:
        """GET a JSON response from an Esri REST endpoint."""
        params = dict(params or {})
        params.setdefault("f", "pjson")

        resp = self.session.get(
            self._build_url(url, params),
            timeout=timeout_tuple(timeout),
            allow_redirects=True,
            verify=self._request_verify(),
        )
        resp.raise_for_status()

        raw = resp.text or ""
        if not raw.strip():
            raise ServiceConnectionError("Empty response from Esri REST service")
        if self._looks_like_html(raw):
            raise ServiceConnectionError("Server returned HTML instead of Esri JSON")

        try:
            data = resp.json()
        except Exception as exc:
            raise ServiceConnectionError(f"Invalid Esri REST JSON: {exc}")

        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            msg = err.get("message", "Esri Server Error")
            details = err.get("details", [])
            raise ServiceConnectionError(f"{msg} {details}")

        return data

    def _post_json_raw(
        self, url: str, params: dict | None = None, timeout: int = DOWNLOAD_TIMEOUT
    ) -> dict:
        """POST form-encoded request to an Esri endpoint (avoids URL length limits)."""
        payload = dict(params or {})
        if self.use_token and self.token:
            payload["token"] = self.token
        resp = self.session.post(
            url,
            data=payload,
            timeout=timeout_tuple(timeout),
            allow_redirects=True,
            verify=self._request_verify(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()

        raw = resp.text or ""
        if self._looks_like_html(raw):
            raise ServiceConnectionError("Server returned HTML instead of Esri JSON")
        try:
            data = resp.json()
        except Exception as exc:
            raise ServiceConnectionError(f"Invalid Esri REST JSON: {exc}")

        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            msg = err.get("message", "Esri Server Error")
            details = err.get("details", [])
            raise ServiceConnectionError(f"{msg} {details}")

        return data

    def _request_json_raw(
        self, url: str, params: dict | None = None, timeout: int = DOWNLOAD_TIMEOUT
    ) -> dict:
        """GET or auto-POST if URL would be too long (proxy stays GET)."""
        params = dict(params or {})
        final_url = self.build_final_url(url, params)

        # POST fallback: only for direct requests. Proxy URLs stay GET because
        # generic proxy endpoints may not accept ArcGIS form POST.
        if not self.use_proxy and len(final_url) > MAX_SAFE_GET_URL_LENGTH:
            return self._post_json_raw(url, params, timeout=timeout)

        try:
            resp = self.session.get(
                final_url,
                timeout=timeout_tuple(timeout),
                allow_redirects=True,
                verify=self._request_verify(),
            )
            resp.raise_for_status()
            raw = resp.text or ""
            if self._looks_like_html(raw):
                raise ServiceConnectionError("Server returned HTML instead of Esri JSON")
            data = resp.json()
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            if (
                not self.use_proxy
                and len(final_url) > MAX_SAFE_GET_URL_LENGTH
                and status in {400, 404, 414, 500}
            ):
                return self._post_json_raw(url, params, timeout=timeout)
            raise ServiceConnectionError(f"HTTP {status}: {exc}")
        except Exception as exc:
            raise ServiceConnectionError(f"Request failed: {exc}")

        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            msg = err.get("message", "Esri Server Error")
            details = err.get("details", [])
            raise ServiceConnectionError(f"{msg} {details}")

        return data

    # =================================================
    # GEOJSON CONVERSION
    # =================================================

    def get_geojson(
        self, url: str, params: dict | None = None, timeout: int = DOWNLOAD_TIMEOUT
    ) -> dict:
        """Fetch data as GeoJSON, with Esri JSON fallback."""
        base_params = dict(params or {})
        base_params.setdefault("returnZ", "true")
        base_params.setdefault("returnM", "true")

        errors = []

        # Try native GeoJSON first
        try:
            geo_params = dict(base_params)
            geo_params["f"] = "geojson"
            data = self._request_json_raw(url, geo_params, timeout=timeout)
            if isinstance(data, dict) and data.get("type") == "FeatureCollection":
                return data
            if isinstance(data, dict) and "features" in data:
                return self._esri_json_to_geojson(data)
        except Exception as exc:
            errors.append(f"geoJSON: {exc}")

        # Fallback: Esri JSON → GeoJSON
        for fmt in ("json", "pjson"):
            try:
                json_params = dict(base_params)
                json_params["f"] = fmt
                data = self._request_json_raw(url, json_params, timeout=timeout)
                converted = self._esri_json_to_geojson(data)
                if isinstance(converted, dict) and converted.get("type") == "FeatureCollection":
                    return converted
                if isinstance(converted, dict) and "features" in converted:
                    return converted
            except Exception as exc:
                errors.append(f"{fmt}: {exc}")

        raise EsriDownloadError("; ".join(errors) if errors else "Connection failed")

    @staticmethod
    def _trim_coord(coord) -> list:
        try:
            if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                return [coord[0], coord[1]]
        except Exception:
            pass
        return coord

    def _esri_geometry_to_geojson(self, geometry: dict) -> dict | None:
        """Convert ArcGIS JSON geometry to GeoJSON geometry."""
        if not isinstance(geometry, dict) or not geometry:
            return None

        if "x" in geometry and "y" in geometry:
            return {"type": "Point", "coordinates": [geometry.get("x"), geometry.get("y")]}

        if "points" in geometry:
            points = [self._trim_coord(p) for p in (geometry.get("points") or []) if p]
            return {"type": "MultiPoint", "coordinates": points}

        if "paths" in geometry:
            paths = geometry.get("paths") or []
            clean = [[self._trim_coord(c) for c in path if c] for path in paths if path]
            if len(clean) == 1:
                return {"type": "LineString", "coordinates": clean[0]}
            return {"type": "MultiLineString", "coordinates": clean}

        if "rings" in geometry:
            rings = geometry.get("rings") or []
            clean = [[self._trim_coord(c) for c in ring if c] for ring in rings if ring]
            return {"type": "Polygon", "coordinates": clean}

        return None

    def _esri_json_to_geojson(self, data: dict) -> dict:
        """Convert Esri JSON feature set to GeoJSON FeatureCollection."""
        if not isinstance(data, dict):
            return data
        if data.get("type") == "FeatureCollection":
            return data

        esri_features = data.get("features")
        if not isinstance(esri_features, list):
            return data

        features = []
        for feature in esri_features:
            if not isinstance(feature, dict):
                continue
            props = feature.get("attributes") or feature.get("properties") or {}
            geom = self._esri_geometry_to_geojson(feature.get("geometry") or {})
            features.append({
                "type": "Feature",
                "properties": props,
                "geometry": geom,
            })

        return {"type": "FeatureCollection", "features": features}

    # =================================================
    # SERVICE INFO
    # =================================================

    def get_service_info(self) -> dict:
        """Get MapServer/FeatureServer root metadata."""
        return self.get_json(self.service_url)

    def get_layer_info(self, layer_id: int) -> dict:
        """Get metadata for a specific sublayer."""
        return self.get_json(f"{self.service_url}/{layer_id}")

    def get_layers_from_service(self) -> list[dict]:
        """Return downloadable child layers from a MapServer/FeatureServer.

        Tries: root layers → /layers endpoint → numeric probe fallback.
        """
        data = self.get_service_info()
        layers = data.get("layers", []) if isinstance(data, dict) else []
        if isinstance(layers, list) and layers:
            return layers

        # Try /layers endpoint
        try:
            layer_data = self.get_json(f"{self.service_url}/layers")
            if isinstance(layer_data, dict):
                for key in ("layers", "tables"):
                    value = layer_data.get(key)
                    if isinstance(value, list) and value:
                        return value
        except Exception:
            logger.debug("Failed to read /layers endpoint for %s", self.service_url, exc_info=True)

        # Probe numeric endpoints
        probed = []
        misses = 0
        for layer_id in range(0, 80):
            try:
                info = self.get_layer_info(layer_id)
                if not isinstance(info, dict) or info.get("error"):
                    misses += 1
                else:
                    name = info.get("name") or info.get("displayField") or f"Layer {layer_id}"
                    is_layer_like = any(
                        k in info for k in ("type", "geometryType", "fields", "capabilities", "drawingInfo")
                    )
                    if is_layer_like or self.can_query_layer(layer_id):
                        probed.append({
                            "id": layer_id,
                            "name": name,
                            "geometryType": info.get("geometryType", ""),
                            "type": info.get("type", ""),
                        })
                        misses = 0
                    else:
                        misses += 1
            except Exception:
                logger.debug("Failed probing layer %s for %s", layer_id, self.service_url, exc_info=True)
                misses += 1
            if misses >= 12 and probed:
                break
            if misses >= 20 and not probed:
                break

        return probed

    # =================================================
    # RENDER-ONLY DETECTION
    # =================================================

    def is_render_only_service(self, info: dict | None = None) -> bool:
        """True when MapServer can render images but has no feature layers."""
        data = info if isinstance(info, dict) else self.get_service_info()
        is_mapserver = self.service_url.lower().endswith("/mapserver")
        layers = data.get("layers") if isinstance(data, dict) else None
        tables = data.get("tables") if isinstance(data, dict) else None
        capabilities = str(data.get("capabilities", "") if isinstance(data, dict) else "")
        formats = str(data.get("supportedImageFormatTypes", "") if isinstance(data, dict) else "")
        return bool(
            is_mapserver
            and isinstance(layers, list) and len(layers) == 0
            and isinstance(tables, list) and len(tables) == 0
            and "map" in capabilities.lower()
            and formats.strip()
        )

    def build_render_only_layer(self, info: dict | None = None) -> dict:
        """Build a pseudo-layer entry for render-only MapServer image export."""
        data = info if isinstance(info, dict) else self.get_service_info()
        document = data.get("documentInfo") or {} if isinstance(data, dict) else {}
        name = (
            data.get("mapName")
            or (document.get("Title") if isinstance(document, dict) else "")
            or "Render-only MapServer"
        )
        formats = str(data.get("supportedImageFormatTypes", "") or "")
        return {
            "id": "__map_image__",
            "name": name,
            "type": "Render-only MapServer",
            "geometryType": "Image Export",
            "downloadMode": "image_export",
            "querySupported": False,
            "imageExportSupported": True,
            "supportedImageFormatTypes": formats,
            "spatialReference": data.get("spatialReference"),
            "initialExtent": data.get("initialExtent"),
            "fullExtent": data.get("fullExtent"),
            "maxImageWidth": data.get("maxImageWidth"),
            "maxImageHeight": data.get("maxImageHeight"),
            "serviceInfo": data,
        }

    # =================================================
    # QUERY CAPABILITY
    # =================================================

    def is_query_supported(self, layer_info: dict) -> bool:
        capabilities = layer_info.get("capabilities", "") or ""
        advanced = layer_info.get("advancedQueryCapabilities", {}) or {}
        return "Query" in capabilities or bool(advanced)

    def can_query_layer(self, layer_id: int) -> bool:
        """Probe the layer query endpoint to confirm it's queryable."""
        try:
            data = self.get_json(
                f"{self.service_url}/{layer_id}/query",
                params={"where": "1=1", "returnCountOnly": "true"},
                timeout=60,
            )
            if isinstance(data, dict) and "error" not in data:
                return "count" in data or data == {}
        except Exception:
            logger.debug("Layer %s count query failed for %s", layer_id, self.service_url, exc_info=True)

        try:
            data = self.get_json(
                f"{self.service_url}/{layer_id}/query",
                params={
                    "where": "1=1",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "resultRecordCount": 1,
                    "f": "json",
                },
                timeout=60,
            )
            if isinstance(data, dict) and "error" not in data:
                return "features" in data or "fields" in data or "geometryType" in data
        except Exception:
            logger.debug("Layer %s sample feature query failed for %s", layer_id, self.service_url, exc_info=True)

        return False

    # =================================================
    # GEOMETRY INFERENCE
    # =================================================

    @staticmethod
    def normalize_geometry_type(geometry_type: str) -> str:
        if not geometry_type:
            return "Unknown"
        text = str(geometry_type).lower()
        if "point" in text:
            return "Point"
        if "polyline" in text or "line" in text:
            return "Polyline"
        if "polygon" in text:
            return "Polygon"
        if "multipoint" in text:
            return "Point"
        return "Unknown"

    def infer_geometry_from_renderer(self, layer_info: dict) -> str:
        try:
            drawing_info = layer_info.get("drawingInfo", {}) or {}
            renderer = drawing_info.get("renderer", {}) or {}
            symbol = renderer.get("symbol", {}) or {}

            if not symbol:
                for key in ["uniqueValueInfos", "classBreakInfos"]:
                    infos = renderer.get(key, []) or []
                    if infos:
                        symbol = infos[0].get("symbol", {}) or {}
                        break

            symbol_type = str(symbol.get("type", "")).lower()
            if "sms" in symbol_type or "markersymbol" in symbol_type:
                return "Point"
            if "sls" in symbol_type or "linesymbol" in symbol_type:
                return "Polyline"
            if "sfs" in symbol_type or "fillsymbol" in symbol_type:
                return "Polygon"
        except Exception:
            logger.debug("Failed to infer geometry from renderer", exc_info=True)
        return "Unknown"

    def infer_geometry_from_geojson_sample(self, layer_id: int) -> str:
        try:
            data = self.get_geojson(
                f"{self.service_url}/{layer_id}/query",
                params={
                    "where": "1=1",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "outSR": "4326",
                    "resultRecordCount": 1,
                },
                timeout=120,
            )
            features = data.get("features", []) or []
            if not features:
                return "Unknown"
            geom = features[0].get("geometry", {}) or {}
            gtype = str(geom.get("type", "")).lower()
            if "point" in gtype:
                return "Point"
            if "line" in gtype:
                return "Polyline"
            if "polygon" in gtype:
                return "Polygon"
        except Exception:
            logger.debug("Failed to infer geometry from GeoJSON sample for layer %s", layer_id, exc_info=True)
        return "Unknown"

    def infer_geometry_from_esri_sample(self, layer_id: int) -> str:
        try:
            data = self.get_json(
                f"{self.service_url}/{layer_id}/query",
                params={
                    "where": "1=1",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "outSR": "4326",
                    "resultRecordCount": 1,
                },
                timeout=120,
            )
            features = data.get("features", []) or []
            if not features:
                return "Unknown"
            geom = features[0].get("geometry", {}) or {}
            if "x" in geom and "y" in geom:
                return "Point"
            if "points" in geom:
                return "Point"
            if "paths" in geom:
                return "Polyline"
            if "rings" in geom:
                return "Polygon"
        except Exception:
            logger.debug("Failed to infer geometry from Esri JSON sample for layer %s", layer_id, exc_info=True)
        return "Unknown"

    def infer_geometry_type(self, layer_id: int, layer_info: dict | None = None) -> str:
        """Infer geometry type from metadata → renderer → sample feature."""
        layer_info = layer_info or self.get_layer_info(layer_id)

        geometry = self.normalize_geometry_type(layer_info.get("geometryType"))
        if geometry != "Unknown":
            return geometry

        geometry = self.infer_geometry_from_renderer(layer_info)
        if geometry != "Unknown":
            return geometry

        geometry = self.infer_geometry_from_geojson_sample(layer_id)
        if geometry != "Unknown":
            return geometry

        return self.infer_geometry_from_esri_sample(layer_id)

    # =================================================
    # FEATURE FETCH
    # =================================================

    def get_feature_count(self, layer_id: int) -> int:
        data = self.get_json(
            f"{self.service_url}/{layer_id}/query",
            params={"where": "1=1", "returnCountOnly": "true"},
        )
        return int(data.get("count", 0))

    def get_object_ids(self, layer_id: int) -> list[int]:
        data = self.get_json(
            f"{self.service_url}/{layer_id}/query",
            params={"where": "1=1", "returnIdsOnly": "true"},
        )
        object_ids = data.get("objectIds") or []
        if not object_ids:
            raise EsriDownloadError("Object ID was not found or the layer is empty.")
        return sorted(object_ids)

    def fetch_features_adaptive(
        self, layer_id: int, object_ids: list[int]
    ) -> list[dict]:
        """Fetch features by ObjectID with recursive split on partial response."""
        ids = list(object_ids or [])
        if not ids:
            return []

        def _fetch_direct(ids_part: list[int]) -> list[dict]:
            data = self.get_geojson(
                f"{self.service_url}/{layer_id}/query",
                params={
                    "objectIds": ",".join(map(str, ids_part)),
                    "outFields": "*",
                    "returnGeometry": "true",
                    "outSR": "4326",
                },
                timeout=180,
            )
            features = data.get("features", []) if isinstance(data, dict) else []
            return features if features else []

        def _feature_object_id(feature: dict) -> int | None:
            attrs = {}
            if isinstance(feature, dict):
                attrs = feature.get("properties") or feature.get("attributes") or {}
            if not isinstance(attrs, dict):
                return None
            for key in ("objectid", "OBJECTID", "ObjectID", "fid", "FID", "id", "ID"):
                if key in attrs:
                    try:
                        return int(attrs[key])
                    except Exception:
                        return attrs[key]
            return None

        def _fetch_recursive(ids_part: list[int]) -> list[dict]:
            ids_part = list(ids_part or [])
            if not ids_part:
                return []

            try:
                features = _fetch_direct(ids_part)
                if len(features) < len(ids_part):
                    if len(ids_part) <= 1:
                        raise EsriDownloadError(
                            f"Empty feature response for ObjectID {ids_part[0]}"
                        )
                    returned_ids = {_feature_object_id(f) for f in features}
                    returned_ids.discard(None)
                    missing = [oid for oid in ids_part if oid not in returned_ids] if returned_ids else ids_part
                    if missing and len(missing) < len(ids_part):
                        return features + _fetch_recursive(missing)
                    raise EsriDownloadError(
                        f"Partial batch response: {len(features)}/{len(ids_part)} features"
                    )
                return features
            except Exception as exc:
                if len(ids_part) <= 1:
                    raise EsriDownloadError(f"ObjectID {ids_part[0]} failed: {exc}")
                mid = max(1, len(ids_part) // 2)
                left = ids_part[:mid]
                right = ids_part[mid:]
                result = []
                result.extend(_fetch_recursive(left))
                result.extend(_fetch_recursive(right))
                return result

        return _fetch_recursive(ids)

    def fetch_features_page(
        self, layer_id: int, offset: int = 0, page_size: int = 500
    ) -> list[dict]:
        """Fetch a page of features using resultOffset pagination."""
        data = self.get_geojson(
            f"{self.service_url}/{layer_id}/query",
            params={
                "where": "1=1",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "resultOffset": int(offset),
                "resultRecordCount": int(page_size),
            },
            timeout=180,
        )
        return data.get("features", [])
