import asyncio
from pathlib import Path
from typing import Optional

import geopandas as gpd

from app.core.exceptions import LayerFieldsUnavailableError, LayerNotFoundError
from app.domain.schemas import BboxFeaturesResponse
from app.infrastructure.db.repository import LayerRepository, UploadSessionRepository


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

        if layer.file_type != 'vector':
            raise LayerFieldsUnavailableError(
                layer.layer_type,
                reason=f"Bbox feature query only available for vector layers, not '{layer.file_type}'"
            )

        source_path = await self._get_source_path(layer)
        if not source_path:
            raise LayerFieldsUnavailableError(layer.layer_type, reason="Source file not found.")

        visible_fields: Optional[list[str]] = None
        if layer.file_metadata and isinstance(layer.file_metadata, dict):
            fields_cfg = layer.file_metadata.get('fields')
            if isinstance(fields_cfg, list):
                visible_fields = [
                    f['original'] for f in fields_cfg
                    if isinstance(f, dict) and f.get('visible', True) and 'original' in f
                ]

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

        return BboxFeaturesResponse(
            layer_id=layer_id,
            count=len(features),
            exceeded=exceeded,
            features=features,
        )

    async def _get_source_path(self, layer) -> Optional[Path]:
        if not layer.upload_session_id:
            return None
        session = await self.session_repo.get_by_id(layer.upload_session_id)
        if not session or not session.final_path:
            return None
        path = Path(session.final_path)
        return path if path.exists() else None

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
