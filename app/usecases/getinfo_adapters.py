"""Per-layer-type strategy adapters for point get-info (GET /layers/{id}/features).

One adapter per layer type replaces the old if/elif dispatch chain so adding or
tuning a layer type is a single-file change. Each adapter returns a GetInfoResult
whose query_hint tells the client what to do: "client" means the layer is rendered
client-side (mvt/geojson/kml/esri_*) and the frontend should read features from its
own already-loaded tiles (see docs/FEATURE_QUERY.md), not issue a backend query.
"""
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse, urlunparse

import geopandas as gpd
import rasterio
import requests
from shapely.geometry import Point

from app.domain.models import Layer
from app.domain.schemas import FeatureQueryResponse

# These are read directly from the client's rendered features (Deck.gl/MapLibre
# querySourceFeatures) and never get a backend feature query. Mirrors the frontend
# contract in docs/FEATURE_QUERY.md.
CLIENT_SIDE_TYPES = {"mvt", "geojson", "kml", "esri_featureserver", "esri_vectortileserver"}


@dataclass
class GetInfoResult:
    response: FeatureQueryResponse
    query_hint: Optional[str] = None


def _empty_vector() -> FeatureQueryResponse:
    return FeatureQueryResponse(type="vector", count=0, features=[])


def _empty_raster() -> FeatureQueryResponse:
    return FeatureQueryResponse(type="raster", count=0, values={})


def _resolve_netloc(netloc: str) -> str:
    """Point outbound GeoServer/WMS calls at the host when running inside Docker.

    Layer URLs are stored as ``localhost:8080`` (correct for the browser on the
    host), but this adapter runs inside the tileserver container where
    ``localhost`` is the container itself. Swap it for ``host.docker.internal``
    (wired up via ``extra_hosts`` in docker-compose) so container->host calls
    reach the host service.
    """
    host = netloc.split(":", 1)[0].lower()
    if host in ("localhost", "127.0.0.1"):
        port = netloc.split(":", 1)[1] if ":" in netloc else ""
        port = f":{port}" if port else ""
        return f"host.docker.internal{port}"
    return netloc


class ClientSideAdapter:
    """Rendered client-side; tell the frontend to query its loaded features."""
    def query(self, layer: Layer, lon: float, lat: float, source_path: Optional[Path] = None) -> GetInfoResult:
        return GetInfoResult(response=_empty_vector(), query_hint="client")


class VectorSourceAdapter:
    def query(self, layer: Layer, lon: float, lat: float, source_path: Optional[Path] = None) -> GetInfoResult:
        if not source_path:
            return GetInfoResult(response=_empty_vector())
        try:
            gdf = gpd.read_file(source_path)
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)
            matching = gdf[gdf.geometry.contains(Point(lon, lat))]
            features = []
            for _, row in matching.iterrows():
                props = row.drop(labels=["geometry"]).to_dict()
                features.append({
                    k: (v if isinstance(v, (str, int, float, bool, type(None))) else str(v))
                    for k, v in props.items()
                })
            return GetInfoResult(response=FeatureQueryResponse(type="vector", count=len(features), features=features))
        except Exception as exc:
            print(f"[vector] Query error: {exc}")
            return GetInfoResult(response=_empty_vector())


class RasterSourceAdapter:
    def query(self, layer: Layer, lon: float, lat: float, source_path: Optional[Path] = None) -> GetInfoResult:
        if not source_path:
            return GetInfoResult(response=_empty_raster())
        try:
            with rasterio.open(source_path) as src:
                row, col = src.index(lon, lat)
                if row < 0 or col < 0 or row >= src.height or col >= src.width:
                    return GetInfoResult(response=_empty_raster())
                sample = list(src.sample([(lon, lat)]))[0]
                values = {f"band_{i+1}": float(val) for i, val in enumerate(sample)}
            return GetInfoResult(response=FeatureQueryResponse(type="raster", count=1, values=values))
        except Exception as exc:
            print(f"[raster] Query error: {exc}")
            return GetInfoResult(response=_empty_raster())


class WmsAdapter:
    def query(self, layer: Layer, lon: float, lat: float, source_path: Optional[Path] = None) -> GetInfoResult:
        wms_url = layer.tile_url_template
        if not wms_url:
            return GetInfoResult(response=_empty_vector())

        parsed = urlparse(wms_url)
        params = {
            key.lower(): values[0] if isinstance(values, list) else values
            for key, values in parse_qs(parsed.query).items()
        }

        layer_name = None
        metadata = layer.file_metadata or {}
        gs_meta = metadata.get("geoserver") or {}
        if isinstance(gs_meta, dict):
            layer_name = gs_meta.get("layer_name")
        if not layer_name:
            mparams = {str(k).lower(): v for k, v in metadata.items()}
            layer_name = mparams.get("layers") or mparams.get("layer")
        if not layer_name:
            layer_name = params.get("layers")
        if not layer_name:
            return GetInfoResult(response=_empty_vector())

        for key in (
            "request", "bbox", "query_layers", "info_format",
            "crs", "srs", "i", "j", "x", "y", "width", "height",
        ):
            params.pop(key, None)

        params["service"] = "WMS"
        params["version"] = params.get("version", "1.3.0")
        params["request"] = "GetFeatureInfo"
        params["layers"] = layer_name
        params["query_layers"] = layer_name
        params["info_format"] = "application/json"

        d = 0.005
        if params["version"].startswith("1.3"):
            params["i"] = 256
            params["j"] = 256
            params["crs"] = "EPSG:4326"
            params["bbox"] = f"{lat-d},{lon-d},{lat+d},{lon+d}"
        else:
            params["x"] = 256
            params["y"] = 256
            params["srs"] = "EPSG:4326"
            params["bbox"] = f"{lon-d},{lat-d},{lon+d},{lat+d}"
        params["width"] = "512"
        params["height"] = "512"

        try:
            base_url = urlunparse((parsed.scheme, _resolve_netloc(parsed.netloc), parsed.path, "", "", ""))
            response = requests.get(base_url, params=params, timeout=10)
            if response.status_code == 200:
                try:
                    data = response.json()
                    if data.get("features"):
                        features = [f["properties"] for f in data["features"] if "properties" in f]
                        return GetInfoResult(response=FeatureQueryResponse(type="vector", count=len(features), features=features))
                except Exception:
                    pass
        except Exception as exc:
            print(f"[wms] GetFeatureInfo error: {exc}")

        return GetInfoResult(response=_empty_vector())


class WfsAdapter:
    def query(self, layer: Layer, lon: float, lat: float, source_path: Optional[Path] = None) -> GetInfoResult:
        wfs_url = layer.tile_url_template
        if not wfs_url:
            return GetInfoResult(response=_empty_vector())
        try:
            parsed = urlparse(wfs_url)
            params = {k: v[0] if isinstance(v, list) else v for k, v in parse_qs(parsed.query).items()}
            layer_name = params.get("typeName") or params.get("typename")
            if not layer_name and layer.file_metadata:
                layer_name = layer.file_metadata.get("layers")
            if not layer_name:
                return GetInfoResult(response=_empty_vector())

            params.update({
                "service": "WFS",
                "version": params.get("version", "2.0.0"),
                "request": "GetFeature",
                "typeName": layer_name,
                "outputFormat": "application/json",
                "bbox": f"{lon-0.01},{lat-0.01},{lon+0.01},{lat+0.01}",
                "srsname": "EPSG:4326",
            })
            base_url = urlunparse((parsed.scheme, _resolve_netloc(parsed.netloc), parsed.path, "", "", ""))
            response = requests.get(base_url, params=params, timeout=10)
            if response.status_code == 200:
                try:
                    data = response.json()
                    if data.get("features"):
                        features = [f["properties"] for f in data["features"] if "properties" in f]
                        return GetInfoResult(response=FeatureQueryResponse(type="vector", count=len(features), features=features))
                except Exception:
                    pass
        except Exception as exc:
            print(f"[wfs] GetFeature error: {exc}")
        return GetInfoResult(response=_empty_vector())


class WmtsAdapter:
    def query(self, layer: Layer, lon: float, lat: float, source_path: Optional[Path] = None) -> GetInfoResult:
        import mercantile

        wmts_url = layer.tile_url_template
        if not wmts_url:
            return GetInfoResult(response=_empty_vector())

        parsed = urlparse(wmts_url)
        url_params = {k: v[0] if isinstance(v, list) else v for k, v in parse_qs(parsed.query).items()}
        layer_name = url_params.get("layer") or url_params.get("LAYER")
        if not layer_name and layer.file_metadata:
            layer_name = layer.file_metadata.get("layers") or layer.file_metadata.get("layer")
        if not layer_name:
            return GetInfoResult(response=_empty_vector())

        zoom = 15
        tile = mercantile.tile(lon, lat, zoom)
        bounds = mercantile.bounds(tile)
        i = int((lon - bounds.west) / (bounds.east - bounds.west) * 255)
        j = int((bounds.north - lat) / (bounds.north - bounds.south) * 255)
        matrix_set = url_params.get("tilematrixset") or url_params.get("TILEMATRIXSET") or "EPSG:3857"
        params = {
            "service": "WMTS",
            "version": "1.0.0",
            "request": "GetFeatureInfo",
            "layer": layer_name,
            "style": url_params.get("style", ""),
            "tilematrixset": matrix_set,
            "tilematrix": f"{matrix_set}:{zoom}",
            "tilerow": tile.y,
            "tilecol": tile.x,
            "i": i,
            "j": j,
            "infoformat": "application/json",
        }
        try:
            base_url = urlunparse((parsed.scheme, _resolve_netloc(parsed.netloc), parsed.path, "", "", ""))
            response = requests.get(base_url, params=params, timeout=10)
            if response.status_code == 200:
                try:
                    data = response.json()
                    if data.get("features"):
                        features = [f["properties"] for f in data["features"] if "properties" in f]
                        return GetInfoResult(response=FeatureQueryResponse(type="vector", count=len(features), features=features))
                except Exception:
                    pass
        except Exception as exc:
            print(f"[wmts] GetFeatureInfo error: {exc}")
        return GetInfoResult(response=_empty_vector())


def _esri_service_base(url: str) -> Optional[str]:
    import re
    m = re.search(r"(.*?/(?:MapServer|ImageServer))", url)
    return m.group(1) if m else None


class EsriMapserverAdapter:
    def query(self, layer: Layer, lon: float, lat: float, source_path: Optional[Path] = None) -> GetInfoResult:
        base = _esri_service_base(layer.tile_url_template or "")
        if not base:
            return GetInfoResult(response=_empty_vector())
        params = {
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "sr": "4326",
            "layers": "all",
            "tolerance": "5",
            "mapExtent": f"{lon-0.01},{lat-0.01},{lon+0.01},{lat+0.01}",
            "imageDisplay": "512,512,96",
            "returnGeometry": "false",
            "f": "json",
        }
        try:
            response = requests.get(f"{base}/identify", params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                features = []
                for r in data.get("results", []):
                    attrs = r.get("attributes", {})
                    if attrs:
                        if r.get("layerName"):
                            attrs = {"_layer": r["layerName"], **attrs}
                        features.append(attrs)
                return GetInfoResult(response=FeatureQueryResponse(type="vector", count=len(features), features=features))
        except Exception as exc:
            print(f"[esri] identify error: {exc}")
        return GetInfoResult(response=_empty_vector())


class EsriImageserverAdapter:
    def query(self, layer: Layer, lon: float, lat: float, source_path: Optional[Path] = None) -> GetInfoResult:
        import json as _json

        base = _esri_service_base(layer.tile_url_template or "")
        if not base:
            return GetInfoResult(response=_empty_raster())
        params = {
            "geometry": _json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryPoint",
            "returnGeometry": "false",
            "f": "json",
        }
        try:
            response = requests.get(f"{base}/identify", params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                value = data.get("value")
                if value is not None and value != "NoData":
                    values = {}
                    for idx, part in enumerate(str(value).replace(",", " ").split(), start=1):
                        try:
                            values[f"band_{idx}"] = float(part)
                        except ValueError:
                            pass
                    if values:
                        return GetInfoResult(response=FeatureQueryResponse(type="raster", count=1, values=values))
        except Exception as exc:
            print(f"[esri-image] identify error: {exc}")
        return GetInfoResult(response=_empty_raster())


class EsriFeatureServerAdapter:
    """Read attributes from the authoritative ESRI FeatureServer sublayer."""
    def query(self, layer: Layer, lon: float, lat: float, source_path: Optional[Path] = None) -> GetInfoResult:
        url = (layer.tile_url_template or "").split("?", 1)[0].rstrip("/")
        if not url or not url.rsplit("/", 1)[-1].isdigit():
            return GetInfoResult(response=_empty_vector())
        params = {
            "f": "json", "where": "1=1", "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint", "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
            "returnGeometry": "false", "resultRecordCount": "20",
        }
        try:
            response = requests.get(f"{url}/query", params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            features = [item.get("attributes", {}) for item in data.get("features", []) if item.get("attributes")]
            return GetInfoResult(response=FeatureQueryResponse(type="vector", count=len(features), features=features))
        except Exception as exc:
            print(f"[esri-feature] query error: {exc}")
            return GetInfoResult(response=_empty_vector())


class FallbackAdapter:
    """Unhandled layer type — no feature source, no client hint (backwards-compatible empty)."""
    def query(self, layer: Layer, lon: float, lat: float, source_path: Optional[Path] = None) -> GetInfoResult:
        return GetInfoResult(response=_empty_vector())


# routing: layer_type (and file_type for source-backed layers) -> adapter
_EXTERNAL_ADAPTERS = {
    "wms": WmsAdapter(),
    "wmts": WmtsAdapter(),
    "wfs": WfsAdapter(),
    "esri_mapserver": EsriMapserverAdapter(),
    "esri_tileserver": EsriMapserverAdapter(),
    "esri_imageserver": EsriImageserverAdapter(),
    "esri_featureserver": EsriFeatureServerAdapter(),
}


def resolve_adapter(layer: Layer) -> object:
    # A local MVT is only its render format: its authoritative source is the
    # uploaded vector dataset and must be queried when a client pick misses.
    if layer.file_type == "vector":
        return VectorSourceAdapter()
    if layer.file_type == "raster":
        return RasterSourceAdapter()
    if layer.file_type == "external":
        adapter = _EXTERNAL_ADAPTERS.get(layer.layer_type)
        if adapter:
            return adapter
        if layer.layer_type in CLIENT_SIDE_TYPES:
            return ClientSideAdapter()
        return FallbackAdapter()
    if layer.layer_type in CLIENT_SIDE_TYPES:
        return ClientSideAdapter()
    return FallbackAdapter()
