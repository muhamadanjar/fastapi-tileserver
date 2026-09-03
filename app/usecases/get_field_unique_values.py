import asyncio
from pathlib import Path
from typing import Optional

import geopandas as gpd

from app.core.exceptions import LayerFieldsUnavailableError, LayerNotFoundError
from app.domain.schemas import FieldUniqueValuesResponse
from app.infrastructure.db.repository import LayerRepository, UploadSessionRepository
from app.usecases.artifact_source import artifact_source_context


class GetFieldUniqueValuesUseCase:
    def __init__(self, layer_repo: LayerRepository, session_repo: UploadSessionRepository):
        self.layer_repo = layer_repo
        self.session_repo = session_repo

    async def execute(
        self,
        layer_id: str,
        field_name: str,
        authorization: Optional[str] = None,
    ) -> FieldUniqueValuesResponse:
        layer = await self.layer_repo.get_by_id(layer_id)
        if not layer:
            raise LayerNotFoundError(layer_id)

        if layer.file_type != 'vector':
            raise LayerFieldsUnavailableError(
                layer.layer_type,
                reason=f"Unique values only available for vector layers, not '{layer.file_type}'"
            )

        if not layer.upload_session_id:
            raise LayerFieldsUnavailableError(layer.layer_type, reason="Source file not found.")
        session = await self.session_repo.get_by_id(layer.upload_session_id)
        if not session:
            raise LayerFieldsUnavailableError(layer.layer_type, reason="Source file not found.")
        async with artifact_source_context(
            session.final_path,
            session.filename,
            authorization,
            f"categorical-values:{layer.id}",
        ) as source_path:
            if not source_path:
                raise LayerFieldsUnavailableError(layer.layer_type, reason="Source file not found.")
            values = await asyncio.to_thread(self._read_unique_values, source_path, field_name)
        return FieldUniqueValuesResponse(layer_id=layer_id, field_name=field_name, values=values)

    @staticmethod
    def _read_unique_values(source_path: Path, field_name: str) -> list[str]:
        gdf = gpd.read_file(source_path)
        if field_name not in gdf.columns:
            raise LayerFieldsUnavailableError(
                'vector',
                reason=f"Field '{field_name}' not found in layer"
            )
        return gdf[field_name].dropna().astype(str).unique().tolist()[:100]
