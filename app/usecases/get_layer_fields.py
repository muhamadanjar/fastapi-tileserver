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
    """

    def __init__(self, layer_repo: LayerRepository, session_repo: UploadSessionRepository):
        self.layer_repo = layer_repo
        self.session_repo = session_repo

    async def execute(self, layer_id: str) -> LayerFieldsResponse:
        layer = await self.layer_repo.get_by_id(layer_id)
        if not layer:
            raise LayerNotFoundError(layer_id)

        source_path = await self._get_source_path(layer)

        if layer.file_type == 'external':
            if layer.layer_type != 'wms':
                raise LayerFieldsUnavailableError(layer.layer_type)
            if source_path:
                fields = await asyncio.to_thread(self._read_vector_fields, source_path)
            else:
                fields = await asyncio.to_thread(self._fetch_wms_remote_fields, layer)
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
    def _fetch_wms_remote_fields(layer: Layer) -> List[str]:
        """Ambil field list layer WMS dari remote via WFS DescribeFeatureType (pola GeoServer)."""
        import requests
        from urllib.parse import urlparse, urlunparse, parse_qs

        meta = layer.file_metadata or {}
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
