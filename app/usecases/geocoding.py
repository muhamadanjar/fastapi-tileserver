"""Geocoding over layer features, backed by Nominatim (OSM).

Handles both directions:
- reverse: feature point -> address (GET /layers/{id}/geocoding?feature_index=N)
- forward: free text -> Nominatim coordinate -> nearby features sorted by distance
  (GET /layers/{id}/geocoding?text=... and GET /geocoding?text=...)
"""
import asyncio
import math
from typing import Optional

import geopandas as gpd
import requests
from shapely.geometry import shape

from app.core.exceptions import LayerNotFoundError, LayerSourceUnavailableError
from app.domain.models import Layer
from app.domain.schemas import (
    ForwardGeocodeResponse,
    ForwardMatch,
    GeocodeHit,
    GlobalGeocodeLayerResult,
    GlobalGeocodeResponse,
    ReverseGeocodeResponse,
)
from app.infrastructure.db.repository import (
    FeatureRepository,
    LayerRepository,
    UploadSessionRepository,
)
from app.infrastructure.services.nominatim_client import NominatimClient
from app.usecases.layer_source import resolve_layer_source_path

EARTH_RADIUS_M = 6_371_000.0


class LayerNotGeocodableError(Exception):
    """Raised when a layer type has no queryable point geometry."""

    def __init__(self, layer_type: str, reason: str = None):
        self.message = reason or (
            f"Layer type '{layer_type}' does not expose geocodable point geometry."
        )
        super().__init__(self.message)


def _haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in meters between two WGS84 coordinates."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _representative_point(geometry: Optional[dict]) -> Optional[tuple[float, float]]:
    """(lon, lat) representative point for a GeoJSON or Esri geometry dict."""
    if not geometry:
        return None
    if "x" in geometry and "y" in geometry:  # Esri point
        return float(geometry["x"]), float(geometry["y"])
    if "points" in geometry and geometry["points"]:  # Esri multipoint
        return float(geometry["points"][0][0]), float(geometry["points"][0][1])
    if "paths" in geometry:  # Esri polyline
        return _esri_path_point(geometry["paths"])
    if "rings" in geometry:  # Esri polygon
        return _esri_ring_centroid(geometry["rings"][0] if geometry["rings"] else None)
    try:  # GeoJSON
        geom = shape(geometry)
    except Exception:
        return None
    if geom.is_empty:
        return None
    p = geom.representative_point()
    return p.x, p.y


def _esri_path_point(paths: list) -> Optional[tuple[float, float]]:
    for path in paths:
        if path:
            x, y = path[0]
            return float(x), float(y)
    return None


def _esri_ring_centroid(ring: Optional[list]) -> Optional[tuple[float, float]]:
    """Area-weighted centroid of a ring (fallback: first vertex)."""
    if not ring or len(ring) < 3:
        return _esri_path_point([ring]) if ring else None
    cx = cy = area2 = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        cross = float(x1) * float(y2) - float(x2) * float(y1)
        area2 += cross
        cx += (float(x1) + float(x2)) * cross
        cy += (float(y1) + float(y2)) * cross
    if area2 == 0:
        return float(ring[0][0]), float(ring[0][1])
    return cx / (3 * area2), cy / (3 * area2)


def _shapely_to_geo(geom) -> Optional[dict]:
    from shapely.geometry import mapping
    return mapping(geom) if geom is not None else None


def _radius_bbox(lon: float, lat: float, radius_m: float) -> tuple[float, float, float, float]:
    """Small WGS84 bbox around (lon, lat) covering the radius."""
    d_lat = radius_m / 111_320.0
    d_lon = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 0.01))
    return lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat


class GeocodingUseCase:
    """Fetches features + Nominatim results for the geocoding endpoints."""

    def __init__(
        self,
        layer_repo: LayerRepository,
        session_repo: UploadSessionRepository,
        feature_repo: Optional[FeatureRepository] = None,
        nominatim: Optional[NominatimClient] = None,
    ):
        self.layer_repo = layer_repo
        self.session_repo = session_repo
        self.feature_repo = feature_repo
        self.nominatim = nominatim or NominatimClient()

    # --- reverse: feature -> address ---

    async def reverse_feature(
        self,
        layer_id: str,
        feature_index: int,
        authorization: Optional[str] = None,
    ) -> ReverseGeocodeResponse:
        layer = await self._layer_or_404(layer_id)
        point = await self._feature_point(layer, feature_index, authorization)
        lon, lat = point
        try:
            result = await asyncio.to_thread(self.nominatim.reverse, lon, lat)
        except requests.RequestException as exc:
            raise LayerSourceUnavailableError(f"Nominatim reverse geocoding gagal: {exc}") from exc
        return ReverseGeocodeResponse(
            feature_index=feature_index,
            longitude=lon,
            latitude=lat,
            address=GeocodeHit(**result) if result else None,
        )

    async def _feature_point(
        self,
        layer: Layer,
        index: int,
        authorization: Optional[str] = None,
    ) -> tuple[float, float]:
        if self._is_survey(layer):
            return await self._survey_point(layer, index)
        if layer.file_type == "vector":
            return await self._local_vector_point(layer, index, authorization)
        if self._is_wfs_queryable(layer):
            features = self._wfs_features(layer, start_index=index, count=2)
            return self._first_point_from_wfs(features, index)
        if layer.layer_type in ("esri_featureserver", "esri_mapserver"):
            features = self._esri_features(layer, result_offset=index, count=2)
            return self._first_point_from_esri(features, index)
        raise LayerNotGeocodableError(layer.layer_type)

    async def _local_vector_point(
        self, layer: Layer, index: int, authorization: Optional[str]
    ) -> tuple[float, float]:
        source = await resolve_layer_source_path(layer, self.session_repo, authorization)
        if not source:
            raise LayerSourceUnavailableError("File sumber layer tidak tersedia.")
        gdf = await asyncio.to_thread(self._read_wgs84, source)
        if index >= len(gdf):
            raise IndexError(f"Feature index {index} is out of range (layer has {len(gdf)} features)")
        geom = gdf.geometry.iloc[index]
        point = _representative_point(_shapely_to_geo(geom)) if geom is not None else None
        if not point:
            raise LayerNotGeocodableError(layer.layer_type, "Feature has no usable geometry")
        return point

    async def _survey_point(self, layer: Layer, index: int) -> tuple[float, float]:
        if not self.feature_repo:
            raise LayerNotGeocodableError(layer.layer_type, "Survey feature access is unavailable")
        features = await self.feature_repo.list_by_project((layer.file_metadata or {}).get("project_id", ""))
        if index >= len(features):
            raise IndexError(f"Feature index {index} is out of range (layer has {len(features)} features)")
        point = _representative_point(features[index].geometry)
        if not point:
            raise LayerNotGeocodableError(layer.layer_type, "Feature has no usable geometry")
        return point

    # --- forward: text -> coordinate -> nearby features ---

    async def forward_layer(
        self,
        layer_id: str,
        text: str,
        radius_m: float = 500,
        limit: int = 20,
        authorization: Optional[str] = None,
    ) -> ForwardGeocodeResponse:
        layer = await self._layer_or_404(layer_id)
        geocoded = await self._geocode_forward(text)
        if not geocoded:
            return ForwardGeocodeResponse(layer_id=layer_id, text=text, geocoded=None, count=0)
        matches = await self._features_near(layer, geocoded.lon, geocoded.lat, radius_m, limit, authorization)
        return ForwardGeocodeResponse(
            layer_id=layer_id, text=text, geocoded=geocoded, count=len(matches), matches=matches,
        )

    async def forward_global(
        self,
        text: str,
        radius_m: float = 500,
        limit: int = 5,
        authorization: Optional[str] = None,
    ) -> GlobalGeocodeResponse:
        geocoded = await self._geocode_forward(text)
        if not geocoded:
            return GlobalGeocodeResponse(text=text, geocoded=None, layers=[])
        layers = await self.layer_repo.list_all()
        results = []
        for layer in layers:
            if not (layer.is_active or layer.is_visible):
                continue
            try:
                matches = await self._features_near(
                    layer, geocoded.lon, geocoded.lat, radius_m, limit, authorization,
                )
            except (LayerNotGeocodableError, LayerSourceUnavailableError, IndexError):
                continue
            if matches:
                results.append(
                    GlobalGeocodeLayerResult(
                        layer_id=layer.id, layer_name=layer.filename, count=len(matches), matches=matches,
                    )
                )
        return GlobalGeocodeResponse(text=text, geocoded=geocoded, layers=results)

    async def _geocode_forward(self, text: str) -> Optional[GeocodeHit]:
        try:
            results = await asyncio.to_thread(self.nominatim.forward, text)
        except requests.RequestException as exc:
            raise LayerSourceUnavailableError(f"Nominatim forward geocoding gagal: {exc}") from exc
        if not results:
            return None
        hit = results[0]
        return GeocodeHit(
            display_name=hit.get("display_name", ""),
            lon=float(hit["lon"]),
            lat=float(hit["lat"]),
            address=hit.get("address"),
        )

    async def _features_near(
        self,
        layer: Layer,
        lon: float,
        lat: float,
        radius_m: float,
        limit: int,
        authorization: Optional[str],
    ) -> list[ForwardMatch]:
        """Return features within radius_m of (lon, lat), nearest first."""
        if self._is_survey(layer):
            return self._near_from_list(
                await self.feature_repo.list_by_project((layer.file_metadata or {}).get("project_id", "")),
                layer, lon, lat, radius_m, limit,
            )
        if layer.file_type == "vector":
            source = await resolve_layer_source_path(layer, self.session_repo, authorization)
            if not source:
                raise LayerSourceUnavailableError("File sumber layer tidak tersedia.")
            gdf = await asyncio.to_thread(self._read_wgs84, source)
            return self._near_from_gdf(gdf, layer, lon, lat, radius_m, limit)
        if self._is_wfs_queryable(layer):
            w, s, e, n = _radius_bbox(lon, lat, radius_m)
            raw = self._wfs_features(layer, west=w, south=s, east=e, north=n, count=limit + 1)
            return self._near_from_wfs(raw, layer, lon, lat, radius_m, limit)
        if layer.layer_type in ("esri_featureserver", "esri_mapserver"):
            w, s, e, n = _radius_bbox(lon, lat, radius_m)
            raw = self._esri_features(layer, west=w, south=s, east=e, north=n, count=limit + 1)
            return self._near_from_esri(raw, layer, lon, lat, radius_m, limit)
        raise LayerNotGeocodableError(layer.layer_type)

    # --- survey feature helpers ---

    @staticmethod
    def _is_survey(layer: Layer) -> bool:
        return layer.layer_type == "geojson" and bool((layer.file_metadata or {}).get("project_id"))

    def _near_from_list(self, features, layer, lon, lat, radius_m, limit) -> list[ForwardMatch]:
        matches = []
        for idx, feature in enumerate(features):
            point = _representative_point(feature.geometry)
            if not point:
                continue
            dist = _haversine(lon, lat, point[0], point[1])
            if dist <= radius_m:
                matches.append(
                    ForwardMatch(
                        feature_index=idx, distance_m=round(dist, 1),
                        properties=dict(feature.attributes), longitude=point[0], latitude=point[1],
                    )
                )
        return sorted(matches, key=lambda m: m.distance_m)[:limit]

    # --- local vector helpers ---

    @staticmethod
    def _read_wgs84(source) -> "gpd.GeoDataFrame":
        gdf = gpd.read_file(source)
        if gdf.crs and gdf.crs.to_epsg() not in (None, 4326):
            gdf = gdf.to_crs(epsg=4326)
        return gdf

    def _near_from_gdf(self, gdf, layer, lon, lat, radius_m, limit) -> list[ForwardMatch]:
        matches = []
        for idx, geom in enumerate(gdf.geometry):
            point = _representative_point(_shapely_to_geo(geom)) if geom is not None else None
            if not point:
                continue
            dist = _haversine(lon, lat, point[0], point[1])
            if dist <= radius_m:
                matches.append(
                    ForwardMatch(
                        feature_index=idx, distance_m=round(dist, 1),
                        properties={k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v)
                                    for k, v in gdf.drop(columns=["geometry"]).iloc[idx].to_dict().items()},
                        longitude=point[0], latitude=point[1],
                    )
                )
        return sorted(matches, key=lambda m: m.distance_m)[:limit]

    # --- WFS helpers (mirrors get_features_in_bbox._query_wfs) ---

    @staticmethod
    def _is_wfs_queryable(layer: Layer) -> bool:
        """True if the layer exposes a WFS GetFeature endpoint (direct WFS or GeoServer-published WMS)."""
        if layer.layer_type == "wfs":
            return True
        if layer.layer_type == "wms" and (layer.file_metadata or {}).get("geoserver", {}).get("wfs_url"):
            return True
        return False

    @staticmethod
    def _wfs_base_url(layer: Layer) -> tuple[str, dict]:
        """Return (base_url, query_params) parsed from the layer's WFS source.
        For WFS external: tile_url_template is the WFS endpoint.
        For WMS geoserver: file_metadata.geoserver.wfs_url is the WFS endpoint.
        """
        from urllib.parse import parse_qs, urlparse, urlunparse
        if layer.layer_type == "wms":
            wfs_url = (layer.file_metadata or {}).get("geoserver", {}).get("wfs_url", "")
        else:
            wfs_url = layer.tile_url_template or ""
        if not wfs_url:
            raise LayerNotGeocodableError(layer.layer_type, "WFS URL is not configured")
        parsed = urlparse(wfs_url)
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        return urlunparse((*parsed[:3], "", "", "")), params

    def _wfs_features(self, layer, start_index: int = None, count: int = None,
                      west=None, south=None, east=None, north=None) -> list[dict]:
        base_url, params = self._wfs_base_url(layer)
        metadata = layer.file_metadata or {}
        layer_name = params.get("typeName") or params.get("typename") or metadata.get("layers")
        if not layer_name:
            gs = metadata.get("geoserver") or {}
            layer_name = gs.get("layer_name")
        if not layer_name:
            raise LayerNotGeocodableError(layer.layer_type, "WFS typeName is not configured")
        params.update({
            "service": "WFS",
            "version": params.get("version", "2.0.0"),
            "request": "GetFeature",
            "typeName": layer_name,
            "outputFormat": "application/json",
            "srsname": "EPSG:4326",
        })
        if west is not None:
            params["bbox"] = f"{west},{south},{east},{north},EPSG:4326"
        if start_index is not None:
            params["startIndex"] = str(start_index)  # WFS 2.0
            params["STARTINDEX"] = str(start_index)  # WFS 1.x
        if count is not None:
            params["count"] = str(count)
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("features") or []

    @staticmethod
    def _first_point_from_wfs(features, index: int) -> tuple[float, float]:
        point = None
        for feature in features:
            point = _representative_point(feature.get("geometry"))
            if point:
                break
        if not point:
            raise IndexError(f"Feature index {index} is out of range for this WFS layer")
        return point

    def _near_from_wfs(self, raw, layer, lon, lat, radius_m, limit) -> list[ForwardMatch]:
        matches = []
        for idx, feature in enumerate(raw):
            point = _representative_point(feature.get("geometry"))
            if not point:
                continue
            dist = _haversine(lon, lat, point[0], point[1])
            if dist <= radius_m:
                matches.append(
                    ForwardMatch(
                        feature_index=idx, distance_m=round(dist, 1),
                        properties=feature.get("properties") or {}, longitude=point[0], latitude=point[1],
                    )
                )
        return sorted(matches, key=lambda m: m.distance_m)[:limit]

    # --- Esri helpers (mirrors get_features_in_bbox._query_esri_service) ---

    def _esri_features(self, layer, result_offset: int = None, count: int = None,
                       west=None, south=None, east=None, north=None) -> list[dict]:
        url = (layer.tile_url_template or "").split("?", 1)[0].rstrip("/")
        if not url or not url.rsplit("/", 1)[-1].isdigit():
            raise LayerNotGeocodableError(layer.layer_type, "Esri service sublayer URL is not configured")
        params = {
            "f": "json",
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
        }
        if west is not None:
            params.update({
                "geometry": f"{west},{south},{east},{north}",
                "geometryType": "esriGeometryEnvelope",
                "spatialRel": "esriSpatialRelIntersects",
                "inSR": "4326",
            })
        if result_offset is not None:
            params["resultOffset"] = str(result_offset)
        if count is not None:
            params["resultRecordCount"] = str(count)
        response = requests.get(f"{url}/query", params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("features") or []

    @staticmethod
    def _first_point_from_esri(features, index: int) -> tuple[float, float]:
        point = None
        for feature in features:
            point = _representative_point(feature.get("geometry"))
            if point:
                break
        if not point:
            raise IndexError(f"Feature index {index} is out of range for this Esri layer")
        return point

    def _near_from_esri(self, raw, layer, lon, lat, radius_m, limit) -> list[ForwardMatch]:
        matches = []
        for idx, feature in enumerate(raw):
            point = _representative_point(feature.get("geometry"))
            if not point:
                continue
            dist = _haversine(lon, lat, point[0], point[1])
            if dist <= radius_m:
                matches.append(
                    ForwardMatch(
                        feature_index=idx, distance_m=round(dist, 1),
                        properties=feature.get("attributes") or {}, longitude=point[0], latitude=point[1],
                    )
                )
        return sorted(matches, key=lambda m: m.distance_m)[:limit]

    # --- shared ---

    async def _layer_or_404(self, layer_id: str) -> Layer:
        layer = await self.layer_repo.get_by_id(layer_id)
        if not layer:
            raise LayerNotFoundError(layer_id)
        return layer


def _radius_bbox(lon: float, lat: float, radius_m: float) -> tuple[float, float, float, float]:
    """Small WGS84 bbox around (lon, lat) covering the radius."""
    d_lat = radius_m / 111_320.0
    d_lon = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 0.01))
    return lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat