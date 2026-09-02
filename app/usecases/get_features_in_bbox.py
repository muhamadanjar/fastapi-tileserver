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
from app.infrastructure.services.upload_artifact_client import UploadArtifactClient


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
    ) -> BboxFeaturesResponse:
        layer = await self.layer_repo.get_by_id(layer_id)
        if not layer:
            raise LayerNotFoundError(layer_id)

        source_path = await self._get_source_path(layer)
        visible_fields: Optional[list[str]] = None
        if layer.file_metadata and isinstance(layer.file_metadata, dict):
            fields_cfg = layer.file_metadata.get('fields')
            if isinstance(fields_cfg, list):
                visible_fields = [
                    f['original'] for f in fields_cfg
                    if isinstance(f, dict) and f.get('visible', True) and 'original' in f
                ]

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

    async def _get_source_path(self, layer) -> Optional[Path]:
        if not layer.upload_session_id:
            return None
        session = await self.session_repo.get_by_id(layer.upload_session_id)
        if not session or not session.final_path:
            return None
        final_path = session.final_path
        if final_path.startswith("artifact://"):
            artifact_id = final_path.removeprefix("artifact://")
            cache_dir = Path(os.getenv("ARTIFACT_CACHE_DIR", "/app/data/artifacts"))
            cache_dir.mkdir(parents=True, exist_ok=True)
            destination = cache_dir / f"{artifact_id}{Path(session.filename or 'source').suffix}"
            if not destination.exists():
                try:
                    with UploadArtifactClient().materialize(artifact_id, session.filename or "artifact.bin") as source:
                        destination.write_bytes(source.read_bytes())
                except Exception:
                    legacy = self._legacy_artifact_path(session.id, session.filename)
                    if not legacy:
                        raise
                    return legacy
            return destination
        path = Path(final_path)
        return path if path.exists() else None

    @staticmethod
    def _legacy_artifact_path(session_id: str, filename: Optional[str]) -> Optional[Path]:
        if not session_id or not filename:
            return None
        root = Path(os.getenv("LEGACY_ARTIFACT_DIR", "/app/data/upload-artifacts"))
        for candidate in (
            root / "objects" / "uploads" / session_id / Path(filename).name,
            root / "uploads" / session_id / Path(filename).name,
        ):
            if candidate.is_file():
                return candidate
        return None

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
