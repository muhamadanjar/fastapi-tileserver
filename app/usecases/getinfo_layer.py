import asyncio
import requests
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse
from typing import Optional

import geopandas as gpd
import rasterio
from shapely.geometry import Point

from app.domain.models import Layer
from app.domain.schemas import FeatureQueryResponse
from app.infrastructure.db.repository import LayerRepository, UploadSessionRepository


class QueryLayerFeaturesUseCase:
    """Unified usecase untuk query features dari berbagai tipe layer."""

    def __init__(self, layer_repo: LayerRepository, session_repo: UploadSessionRepository):
        self.layer_repo = layer_repo
        self.session_repo = session_repo

    async def execute(self, layer_id: str, lon: float, lat: float) -> FeatureQueryResponse:
        """Query features dari layer berdasarkan koordinat."""
        layer = await self.layer_repo.get_by_id(layer_id)
        if not layer:
            return FeatureQueryResponse(type='vector', count=0, features=[])

        response = await self._dispatch(layer, lon, lat)
        # Field config dari file_metadata.fields berlaku untuk SEMUA layer type
        return self._apply_field_configs(layer, response)

    async def _dispatch(self, layer: Layer, lon: float, lat: float) -> FeatureQueryResponse:
        """Dispatch ke handler yang sesuai berdasarkan layer type."""
        if layer.file_type == 'external':
            if layer.layer_type == 'wms':
                return await asyncio.to_thread(self._query_wms, layer, lon, lat)
            elif layer.layer_type == 'wmts':
                return await asyncio.to_thread(self._query_wmts, layer, lon, lat)
            elif layer.layer_type == 'wfs':
                return await asyncio.to_thread(self._query_wfs, layer, lon, lat)
            elif layer.layer_type in ('esri_mapserver', 'esri_tileserver'):
                return await asyncio.to_thread(self._query_esri_mapserver, layer, lon, lat)
            elif layer.layer_type == 'esri_imageserver':
                return await asyncio.to_thread(self._query_esri_imageserver, layer, lon, lat)
            else:
                return FeatureQueryResponse(type='vector', count=0, features=[])
        elif layer.file_type == 'vector':
            source_path = await self._get_source_path(layer)
            return await asyncio.to_thread(self._query_vector, layer, source_path, lon, lat)
        elif layer.file_type == 'raster':
            source_path = await self._get_source_path(layer)
            return await asyncio.to_thread(self._query_raster, source_path, lon, lat)
        else:
            return FeatureQueryResponse(type='vector', count=0, features=[])

    @staticmethod
    def _apply_field_configs(layer: Layer, response: FeatureQueryResponse) -> FeatureQueryResponse:
        """Filter response fields sesuai file_metadata.fields (visible only).

        Key tetap pakai nama original — frontend yang map ke label saat render.
        """
        field_configs = (layer.file_metadata or {}).get('fields')
        if not field_configs:
            return response

        visible = {
            fc['original']
            for fc in field_configs
            if isinstance(fc, dict) and fc.get('original') and fc.get('visible', True)
        }
        if not visible:
            return response

        if response.type == 'vector' and response.features:
            filtered = [
                {k: v for k, v in feat.items() if k in visible or k == '_layer'}
                for feat in response.features
            ]
            return FeatureQueryResponse(type='vector', count=len(filtered), features=filtered)

        if response.type == 'raster' and response.values:
            vals = {k: v for k, v in response.values.items() if k in visible}
            # Filter hanya jika ada band yang match config — jangan blank-kan response
            if vals:
                return FeatureQueryResponse(type='raster', count=1, values=vals)

        return response

    async def _get_source_path(self, layer: Layer) -> Optional[Path]:
        """Get local file path dari upload session."""
        if not layer.upload_session_id:
            return None
        session = await self.session_repo.get_by_id(layer.upload_session_id)
        if not session or not session.final_path:
            return None
        path = Path(session.final_path)
        return path if path.exists() else None

    def _query_vector(self, layer: Layer, source_path: Optional[Path], lon: float, lat: float) -> FeatureQueryResponse:
        """Query vector layer menggunakan GeoPandas."""
        if not source_path:
            return FeatureQueryResponse(type='vector', count=0, features=[])

        try:
            gdf = gpd.read_file(source_path)
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)

            point = Point(lon, lat)
            matching = gdf[gdf.geometry.contains(point)]

            # Field filtering dilakukan terpusat di _apply_field_configs — return raw properties
            features = []
            for _, row in matching.iterrows():
                props = row.drop(labels=['geometry']).to_dict()
                cleaned = {
                    k: (v if isinstance(v, (str, int, float, bool, type(None))) else str(v))
                    for k, v in props.items()
                }
                features.append(cleaned)

            return FeatureQueryResponse(type='vector', count=len(features), features=features)
        except Exception as exc:
            print(f"[vector] Query error: {exc}")
            return FeatureQueryResponse(type='vector', count=0, features=[])

    def _query_raster(self, source_path: Optional[Path], lon: float, lat: float) -> FeatureQueryResponse:
        """Query raster layer menggunakan Rasterio."""
        if not source_path:
            return FeatureQueryResponse(type='raster', count=0, values={})

        try:
            with rasterio.open(source_path) as src:
                row, col = src.index(lon, lat)
                if row < 0 or col < 0 or row >= src.height or col >= src.width:
                    return FeatureQueryResponse(type='raster', count=0, values={})

                sample = list(src.sample([(lon, lat)]))[0]
                values = {f'band_{i+1}': float(val) for i, val in enumerate(sample)}

            return FeatureQueryResponse(type='raster', count=1, values=values)
        except Exception as exc:
            print(f"[raster] Query error: {exc}")
            return FeatureQueryResponse(type='raster', count=0, values={})

    def _query_wms(self, layer: Layer, lon: float, lat: float) -> FeatureQueryResponse:
        """Query WMS layer menggunakan GetFeatureInfo."""
        wms_url = layer.tile_url_template
        if not wms_url:
            return FeatureQueryResponse(type='vector', count=0, features=[])

        # Parse URL untuk handle existing params
        parsed = urlparse(wms_url)
        existing_params = parse_qs(parsed.query)
        params = {k: v[0] if isinstance(v, list) else v for k, v in existing_params.items()}

        # Get layer name dari metadata
        layer_name = None
        if layer.file_metadata and 'geoserver' in layer.file_metadata:
            layer_name = layer.file_metadata.get('geoserver', {}).get('layer_name')
        if not layer_name and layer.file_metadata and 'layers' in layer.file_metadata:
            layer_name = layer.file_metadata['layers']
        if not layer_name:
            layer_name = params.get('layers') or params.get('LAYERS')

        if not layer_name:
            return FeatureQueryResponse(type='vector', count=0, features=[])

        # Build GetFeatureInfo request
        params['service'] = 'WMS'
        params['version'] = params.get('version', '1.3.0')
        params['request'] = 'GetFeatureInfo'
        params['layers'] = layer_name
        params['query_layers'] = layer_name
        params['info_format'] = 'application/json'

        # BBOX kecil supaya resolusi pixel tinggi — ±1° membuat fitur kecil sub-pixel
        # (512px / 0.01° ≈ 2m per pixel)
        d = 0.005
        # Coordinate names depend on WMS version
        if params['version'].startswith('1.3'):
            params['i'] = 256
            params['j'] = 256
            params['crs'] = 'EPSG:4326'
            # WMS 1.3.0 + EPSG:4326 pakai axis order lat,lon
            params['bbox'] = f"{lat-d},{lon-d},{lat+d},{lon+d}"
        else:
            params['x'] = 256
            params['y'] = 256
            params['srs'] = 'EPSG:4326'
            params['bbox'] = f"{lon-d},{lat-d},{lon+d},{lat+d}"

        params['width'] = '512'
        params['height'] = '512'

        try:
            base_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
            response = requests.get(base_url, params=params, timeout=10)

            if response.status_code == 200:
                try:
                    data = response.json()
                    if 'features' in data and data['features']:
                        features = []
                        for feature in data['features']:
                            if 'properties' in feature:
                                features.append(feature['properties'])
                        return FeatureQueryResponse(type='vector', count=len(features), features=features)
                except:
                    pass
        except Exception as exc:
            print(f"[wms] GetFeatureInfo error: {exc}")

        return FeatureQueryResponse(type='vector', count=0, features=[])

    def _query_wfs(self, layer: Layer, lon: float, lat: float) -> FeatureQueryResponse:
        """Query WFS layer menggunakan GetFeature dengan spatial filter."""
        wfs_url = layer.tile_url_template
        if not wfs_url:
            return FeatureQueryResponse(type='vector', count=0, features=[])

        try:
            # Parse existing params
            parsed = urlparse(wfs_url)
            existing_params = parse_qs(parsed.query)
            params = {k: v[0] if isinstance(v, list) else v for k, v in existing_params.items()}

            layer_name = params.get('typeName') or params.get('typename')
            if not layer_name and layer.file_metadata:
                layer_name = layer.file_metadata.get('layers')

            if not layer_name:
                return FeatureQueryResponse(type='vector', count=0, features=[])

            # Build GetFeature request dengan BBOX filter
            params['service'] = 'WFS'
            params['version'] = params.get('version', '2.0.0')
            params['request'] = 'GetFeature'
            params['typeName'] = layer_name
            params['outputFormat'] = 'application/json'
            params['bbox'] = f"{lon-0.01},{lat-0.01},{lon+0.01},{lat+0.01}"
            params['srsname'] = 'EPSG:4326'

            base_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
            response = requests.get(base_url, params=params, timeout=10)

            if response.status_code == 200:
                try:
                    data = response.json()
                    if 'features' in data and data['features']:
                        features = []
                        for feature in data['features']:
                            if 'properties' in feature:
                                features.append(feature['properties'])
                        return FeatureQueryResponse(type='vector', count=len(features), features=features)
                except:
                    pass
        except Exception as exc:
            print(f"[wfs] GetFeature error: {exc}")

        return FeatureQueryResponse(type='vector', count=0, features=[])

    def _query_wmts(self, layer: Layer, lon: float, lat: float) -> FeatureQueryResponse:
        """Query WMTS layer menggunakan GetFeatureInfo (KVP, best-effort)."""
        import mercantile

        wmts_url = layer.tile_url_template
        if not wmts_url:
            return FeatureQueryResponse(type='vector', count=0, features=[])

        parsed = urlparse(wmts_url)
        existing_params = parse_qs(parsed.query)
        url_params = {k: v[0] if isinstance(v, list) else v for k, v in existing_params.items()}

        layer_name = url_params.get('layer') or url_params.get('LAYER')
        if not layer_name and layer.file_metadata:
            layer_name = layer.file_metadata.get('layers') or layer.file_metadata.get('layer')
        if not layer_name:
            return FeatureQueryResponse(type='vector', count=0, features=[])

        # Compute tile coords + pixel offset pada zoom tetap (WebMercator)
        zoom = 15
        tile = mercantile.tile(lon, lat, zoom)
        bounds = mercantile.bounds(tile)
        i = int((lon - bounds.west) / (bounds.east - bounds.west) * 255)
        j = int((bounds.north - lat) / (bounds.north - bounds.south) * 255)

        matrix_set = url_params.get('tilematrixset') or url_params.get('TILEMATRIXSET') or 'EPSG:3857'
        params = {
            'service': 'WMTS',
            'version': '1.0.0',
            'request': 'GetFeatureInfo',
            'layer': layer_name,
            'style': url_params.get('style', ''),
            'tilematrixset': matrix_set,
            'tilematrix': f"{matrix_set}:{zoom}",
            'tilerow': tile.y,
            'tilecol': tile.x,
            'i': i,
            'j': j,
            'infoformat': 'application/json',
        }

        try:
            base_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
            response = requests.get(base_url, params=params, timeout=10)
            if response.status_code == 200:
                try:
                    data = response.json()
                    if 'features' in data and data['features']:
                        features = [f['properties'] for f in data['features'] if 'properties' in f]
                        return FeatureQueryResponse(type='vector', count=len(features), features=features)
                except:
                    pass
        except Exception as exc:
            print(f"[wmts] GetFeatureInfo error: {exc}")

        return FeatureQueryResponse(type='vector', count=0, features=[])

    @staticmethod
    def _esri_service_base(url: str) -> Optional[str]:
        """Ambil base URL Esri service (sampai MapServer/ImageServer), buang /tile/... dan query string."""
        import re
        m = re.search(r'(.*?/(?:MapServer|ImageServer))', url)
        return m.group(1) if m else None

    def _query_esri_mapserver(self, layer: Layer, lon: float, lat: float) -> FeatureQueryResponse:
        """Query Esri MapServer/TileServer menggunakan identify endpoint."""
        base = self._esri_service_base(layer.tile_url_template or '')
        if not base:
            return FeatureQueryResponse(type='vector', count=0, features=[])

        params = {
            'geometry': f"{lon},{lat}",
            'geometryType': 'esriGeometryPoint',
            'sr': '4326',
            'layers': 'all',
            'tolerance': '5',
            'mapExtent': f"{lon-0.01},{lat-0.01},{lon+0.01},{lat+0.01}",
            'imageDisplay': '512,512,96',
            'returnGeometry': 'false',
            'f': 'json',
        }

        try:
            response = requests.get(f"{base}/identify", params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                features = []
                for r in results:
                    attrs = r.get('attributes', {})
                    if attrs:
                        if r.get('layerName'):
                            attrs = {'_layer': r['layerName'], **attrs}
                        features.append(attrs)
                return FeatureQueryResponse(type='vector', count=len(features), features=features)
        except Exception as exc:
            print(f"[esri] identify error: {exc}")

        return FeatureQueryResponse(type='vector', count=0, features=[])

    def _query_esri_imageserver(self, layer: Layer, lon: float, lat: float) -> FeatureQueryResponse:
        """Query Esri ImageServer menggunakan identify endpoint — return pixel values."""
        import json as _json

        base = self._esri_service_base(layer.tile_url_template or '')
        if not base:
            return FeatureQueryResponse(type='raster', count=0, values={})

        params = {
            'geometry': _json.dumps({'x': lon, 'y': lat, 'spatialReference': {'wkid': 4326}}),
            'geometryType': 'esriGeometryPoint',
            'returnGeometry': 'false',
            'f': 'json',
        }

        try:
            response = requests.get(f"{base}/identify", params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                value = data.get('value')
                if value is not None and value != 'NoData':
                    values = {}
                    parts = str(value).replace(',', ' ').split()
                    for idx, part in enumerate(parts, start=1):
                        try:
                            values[f'band_{idx}'] = float(part)
                        except ValueError:
                            pass
                    if values:
                        return FeatureQueryResponse(type='raster', count=1, values=values)
        except Exception as exc:
            print(f"[esri-image] identify error: {exc}")

        return FeatureQueryResponse(type='raster', count=0, values={})
