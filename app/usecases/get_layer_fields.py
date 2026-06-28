import asyncio
from pathlib import Path
from typing import List, Optional

import geopandas as gpd
import rasterio

from app.core.exceptions import LayerFieldsUnavailableError, LayerNotFoundError
from app.domain.models import Layer
from app.domain.schemas import LayerFieldsResponse
from app.infrastructure.db.repository import LayerRepository, UploadSessionRepository


class GetLayerFieldsUseCase:
    """Ambil daftar field/atribut sebuah layer.

    Sumber field per tipe layer:
    - vector lokal  → kolom file sumber (geopandas)
    - raster lokal  → band_1..band_N (rasterio)
    - external WMS  → file sumber lokal kalau ada (publish flow),
                      else remote WFS DescribeFeatureType (pola GeoServer)
    - external ESRI MapServer/FeatureServer → file sumber lokal atau REST API
    """

    def __init__(self, layer_repo: LayerRepository, session_repo: UploadSessionRepository):
        self.layer_repo = layer_repo
        self.session_repo = session_repo

    async def execute(self, layer_id: str, layer_index: Optional[int] = None) -> LayerFieldsResponse:
        layer = await self.layer_repo.get_by_id(layer_id)
        if not layer:
            raise LayerNotFoundError(layer_id)

        source_path = await self._get_source_path(layer)

        if layer.file_type == 'external':
            if layer.layer_type not in ('wms', 'esri_mapserver', 'esri_featureserver'):
                raise LayerFieldsUnavailableError(layer.layer_type)
            if source_path:
                fields = await asyncio.to_thread(self._read_vector_fields, source_path)
            else:
                # Pass layer_index ke fetch_remote_fields
                meta = layer.file_metadata or {}
                if layer_index is not None:
                    meta = {**meta, 'layerIndex': layer_index}
                fields = await asyncio.to_thread(self._fetch_remote_fields, layer, meta)
            return LayerFieldsResponse(layer_id=layer_id, fields=fields)

        if not source_path:
            raise LayerFieldsUnavailableError(layer.layer_type, reason="Source file not found.")

        if layer.file_type == 'vector':
            fields = await asyncio.to_thread(self._read_vector_fields, source_path)
        else:
            fields = await asyncio.to_thread(self._read_raster_fields, source_path)

        return LayerFieldsResponse(layer_id=layer_id, fields=fields)

    async def _get_source_path(self, layer: Layer) -> Optional[Path]:
        if not layer.upload_session_id:
            return None
        session = await self.session_repo.get_by_id(layer.upload_session_id)
        if not session or not session.final_path:
            return None
        path = Path(session.final_path)
        return path if path.exists() else None

    @staticmethod
    def _read_vector_fields(source_path: Path) -> List[str]:
        gdf = gpd.read_file(source_path)
        return gdf.columns.drop('geometry').tolist()

    @staticmethod
    def _read_raster_fields(source_path: Path) -> List[str]:
        with rasterio.open(source_path) as src:
            return [f'band_{i}' for i in range(1, src.count + 1)]

    @staticmethod
    def _fetch_remote_fields(layer: Layer, meta: Optional[dict] = None) -> List[str]:
        """Ambil field list dari remote WMS/ESRI via WFS DescribeFeatureType atau FeatureServer REST API."""
        import requests
        from urllib.parse import urlparse, urlunparse, parse_qs

        meta = meta or layer.file_metadata or {}

        # Handle ESRI FeatureServer
        if layer.layer_type == 'esri_featureserver':
            return GetLayerFieldsUseCase._fetch_esri_featureserver_fields(layer, meta)

        # Handle ESRI MapServer
        if layer.layer_type == 'esri_mapserver':
            return GetLayerFieldsUseCase._fetch_esri_mapserver_fields(layer, meta)

        # Handle WMS (default behavior)
        gs = meta.get('geoserver') or {}
        layer_name = gs.get('layer_name') or meta.get('layers')
        parsed = urlparse(layer.tile_url_template or '')
        if not layer_name:
            q = {k.lower(): v[0] for k, v in parse_qs(parsed.query).items()}
            layer_name = q.get('layers')
        if not layer_name:
            return []

        base_url = gs.get('wfs_url') or urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
        try:
            resp = requests.get(base_url, params={
                'service': 'WFS',
                'version': '2.0.0',
                'request': 'DescribeFeatureType',
                'typeNames': layer_name,
                'outputFormat': 'application/json',
            }, timeout=10)
            if resp.status_code == 200:
                feature_types = resp.json().get('featureTypes') or []
                if feature_types:
                    props = feature_types[0].get('properties') or []
                    return [
                        p['name'] for p in props
                        if p.get('name') and not str(p.get('type', '')).startswith('gml:')
                    ]
        except Exception:
            pass
        return []

    @staticmethod
    def _fetch_esri_featureserver_fields(layer: Layer, meta: dict) -> List[str]:
        """Ambil field list dari ESRI FeatureServer via REST API."""
        import requests

        url = layer.tile_url_template
        if not url:
            return []

        try:
            # ESRI FeatureServer query endpoint
            resp = requests.get(f'{url}?f=json', timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                fields = data.get('fields') or []
                return [f['name'] for f in fields if f.get('name')]
        except Exception:
            pass
        return []

    @staticmethod
    def _fetch_esri_mapserver_fields(layer: Layer, meta: dict) -> List[str]:
        """Ambil field list dari ESRI MapServer via REST API.

        MapServer bisa multiple layers, layer index bisa dari metadata atau default ke 0.
        Format: {base_url}/0?f=json, {base_url}/1?f=json, dst.
        """
        import requests

        url = layer.tile_url_template
        if not url:
            return []

        # Get layer index from metadata, default ke 0
        layer_index = meta.get('layerIndex', 0) if meta else 0

        try:
            # ESRI MapServer query endpoint dengan layer index
            resp = requests.get(f'{url}/{layer_index}?f=json', timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                fields = data.get('fields') or []
                return [f['name'] for f in fields if f.get('name')]
        except Exception:
            pass
        return []
