import asyncio
import os
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse, urlunparse

import geopandas as gpd
import requests

from app.core.exceptions import LayerNotFoundError
from app.domain.schemas import BboxFeaturesResponse
from app.infrastructure.db.repository import LayerRepository, UploadSessionRepository
from app.usecases.artifact_source import artifact_source_context


class GetFeaturesInBboxUseCase:
    def __init__(self, layer_repo: LayerRepository, session_repo: UploadSessionRepository):
        self.layer_repo = layer_repo
        self.session_repo = session_repo

    async def execute(
        self,
        layer_id: str,
        west: float,
        south: float,
        east: float,
        north: float,
        limit: int = 200,
        authorization: Optional[str] = None,
    ) -> BboxFeaturesResponse:
        layer = await self.layer_repo.get_by_id(layer_id)
        if not layer:
            raise LayerNotFoundError(layer_id)

        session = await self.session_repo.get_by_id(layer.upload_session_id) if layer.upload_session_id else None
        visible_fields: Optional[list[str]] = None
        if layer.file_metadata and isinstance(layer.file_metadata, dict):
            fields_cfg = layer.file_metadata.get('fields')
            if isinstance(fields_cfg, list):
                visible_fields = [
                    f['original'] for f in fields_cfg
                    if isinstance(f, dict) and f.get('visible', True) and 'original' in f
                ]

        async with artifact_source_context(
            session.final_path if session else None,
            session.filename if session else None,
            authorization,
            f"bbox-features:{layer.id}",
        ) as source_path:
            if source_path and layer.file_type == 'vector':
                features, exceeded = await asyncio.to_thread(
                    self._read_features_in_bbox,
                    source_path,
                    west,
                    south,
                    east,
                    north,
                    limit,
                    visible_fields,
                )
            elif layer.layer_type == 'wfs':
                features, exceeded = await asyncio.to_thread(
                    self._query_wfs,
                    layer,
                    west,
                    south,
                    east,
                    north,
                    limit,
                    visible_fields,
                )
            elif layer.layer_type in {'esri_featureserver', 'esri_mapserver'}:
                features, exceeded = await asyncio.to_thread(
                    self._query_esri_service,
                    layer,
                    west,
                    south,
                    east,
                    north,
                    limit,
                    visible_fields,
                )
            else:
                return self._not_queryable(layer, source_path)

        return BboxFeaturesResponse(
            layer_id=layer_id,
            count=len(features),
            exceeded=exceeded,
            features=features,
        )

    @staticmethod
    def _not_queryable(layer, source_path: Optional[Path]) -> BboxFeaturesResponse:
        if layer.file_type == 'raster' or layer.layer_type == 'esri_imageserver':
            reason = 'Raster bbox feature queries are not available; use raster statistics or pixel sampling.'
        elif source_path:
            reason = f"Local source is not a vector dataset (file_type='{layer.file_type}')."
        elif layer.layer_type in {'wms', 'wmts', 'tile', 'mvt', 'esri_tileserver', 'esri_vectortileserver'}:
            reason = 'This render-only layer does not expose a standard bbox feature query.'
        elif layer.layer_type == 'postgis':
            reason = 'PostGIS bbox querying requires a configured geodata table adapter.'
        else:
            reason = 'No queryable vector source is available for this layer.'
        return BboxFeaturesResponse(
            layer_id=layer.id,
            count=0,
            exceeded=False,
            features=[],
            queryable=False,
            reason=reason,
        )

    @staticmethod
    def _read_features_in_bbox(
        source_path: Path,
        west: float,
        south: float,
        east: float,
        north: float,
        limit: int,
        visible_fields: Optional[list[str]],
    ) -> tuple[list[dict], bool]:
        gdf = gpd.read_file(source_path)
        clipped = gdf.cx[west:east, south:north]
        rows = clipped.drop(columns=['geometry'], errors='ignore')

        if visible_fields:
            keep = [f for f in visible_fields if f in rows.columns]
            if keep:
                rows = rows[keep]

        all_records = rows.astype(str).to_dict(orient='records')
        exceeded = len(all_records) > limit
        return all_records[:limit], exceeded

    @staticmethod
    def _query_wfs(layer, west, south, east, north, limit, visible_fields) -> tuple[list[dict], bool]:
        """Read WFS features using the standard GetFeature BBOX request."""
        if not layer.tile_url_template:
            return [], False
        parsed = urlparse(layer.tile_url_template)
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        metadata = layer.file_metadata or {}
        layer_name = params.get('typeName') or params.get('typename') or metadata.get('layers')
        if not layer_name:
            return [], False
        params.update({
            'service': 'WFS',
            'version': params.get('version', '2.0.0'),
            'request': 'GetFeature',
            'typeName': layer_name,
            'outputFormat': 'application/json',
            'srsname': 'EPSG:4326',
            'bbox': f'{west},{south},{east},{north},EPSG:4326',
            'count': str(limit + 1),
        })
        response = requests.get(urlunparse((*parsed[:3], '', '', '')), params=params, timeout=10)
        response.raise_for_status()
        raw_features = response.json().get('features') or []
        return GetFeaturesInBboxUseCase._properties(raw_features, limit, visible_fields)

    @staticmethod
    def _query_esri_service(layer, west, south, east, north, limit, visible_fields) -> tuple[list[dict], bool]:
        """Read a queryable ESRI service layer. A concrete service sublayer is required."""
        url = (layer.tile_url_template or '').split('?', 1)[0].rstrip('/')
        if not url or not url.rsplit('/', 1)[-1].isdigit():
            return [], False
        params = {
            'f': 'json',
            'where': '1=1',
            'geometry': f'{west},{south},{east},{north}',
            'geometryType': 'esriGeometryEnvelope',
            'spatialRel': 'esriSpatialRelIntersects',
            'inSR': '4326',
            'outFields': '*',
            'returnGeometry': 'false',
            'resultRecordCount': limit + 1,
        }
        response = requests.get(f'{url}/query', params=params, timeout=10)
        response.raise_for_status()
        return GetFeaturesInBboxUseCase._properties(response.json().get('features') or [], limit, visible_fields, 'attributes')

    @staticmethod
    def _properties(raw_features, limit, visible_fields, property_key='properties') -> tuple[list[dict], bool]:
        records = [feature.get(property_key, {}) for feature in raw_features if feature.get(property_key) is not None]
        if visible_fields:
            records = [{key: value for key, value in record.items() if key in visible_fields} for record in records]
        exceeded = len(records) > limit
        return records[:limit], exceeded
