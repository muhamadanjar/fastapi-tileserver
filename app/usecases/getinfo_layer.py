import asyncio
import os
import requests  # kept for tests/test_wms_feature_info.py monkeypatch target
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from app.core.exceptions import LayerSourceUnavailableError
from app.domain.models import Layer
from app.domain.schemas import FeatureQueryResponse
from app.infrastructure.db.repository import LayerRepository, UploadSessionRepository
from app.infrastructure.services.upload_artifact_client import UploadArtifactClient
from app.usecases.getinfo_adapters import (
    EsriImageserverAdapter,
    EsriMapserverAdapter,
    WfsAdapter,
    WmsAdapter,
    WmtsAdapter,
    resolve_adapter,
)


class QueryLayerFeaturesUseCase:
    """Unified usecase untuk query features dari berbagai tipe layer.

    Per-layer-type behaviour lives in the strategy adapters (getinfo_adapters.py);
    this usecase only resolves the right adapter and applies shared post-processing.
    """

    def __init__(self, layer_repo: LayerRepository, session_repo: UploadSessionRepository):
        self.layer_repo = layer_repo
        self.session_repo = session_repo

    async def execute(
        self,
        layer_id: str,
        lon: float,
        lat: float,
        authorization: Optional[str] = None,
    ) -> FeatureQueryResponse:
        """Query features dari layer berdasarkan koordinat."""
        layer = await self.layer_repo.get_by_id(layer_id)
        if not layer:
            return FeatureQueryResponse(type='vector', count=0, features=[])

        result = await self._dispatch(layer, lon, lat, authorization=authorization)
        response = result.response
        # Field config dari file_metadata.fields berlaku untuk SEMUA layer type
        response = self._apply_field_configs(layer, response)
        if result.query_hint and not response.query_hint:
            response.query_hint = result.query_hint
        return response

    @asynccontextmanager
    async def _source_context(self, layer: Layer, authorization: Optional[str] = None):
        """Yield a local path the source adapter can read.

        ``final_path`` may be ``artifact://<id>`` (artifact-backed upload) instead of a
        local file. In that case download the artifact once into a persistent cache
        keyed by artifact id, so repeated get-info clicks don't re-fetch on every hit.
        """
        if not layer.upload_session_id:
            yield None
            return
        session = await self.session_repo.get_by_id(layer.upload_session_id)
        if not session or not session.final_path:
            yield None
            return
        final_path = session.final_path
        if final_path.startswith("artifact://"):
            artifact_id = final_path.removeprefix("artifact://")
            cache_dir = Path(os.getenv("ARTIFACT_CACHE_DIR", "/app/data/artifacts"))
            cache_dir.mkdir(parents=True, exist_ok=True)
            suffix = Path(session.filename or "source").suffix
            dest = cache_dir / f"{artifact_id}{suffix}"
            if not dest.exists():
                client = UploadArtifactClient()
                try:
                    with client.materialize(artifact_id, session.filename or "artifact.bin") as tmp:
                        dest.write_bytes(tmp.read_bytes())
                except Exception as exc:
                    if authorization:
                        lease_id = None
                        try:
                            grant_id = await asyncio.to_thread(
                                client.create_user_grant, artifact_id, authorization,
                            )
                            lease = await asyncio.to_thread(
                                client.acquire_lease,
                                artifact_id,
                                grant_id,
                                f"feature-info:{layer.id}:{uuid.uuid4()}",
                            )
                            lease_id = str(lease["lease_id"])
                            with client.materialize(artifact_id, session.filename or "artifact.bin") as tmp:
                                dest.write_bytes(tmp.read_bytes())
                        except Exception as renewal_exc:
                            legacy = self._legacy_artifact_path(session.id, session.filename)
                            if legacy:
                                yield legacy
                                return
                            raise LayerSourceUnavailableError(
                                "File sumber artifact tidak tersedia untuk Get Info."
                            ) from renewal_exc
                        finally:
                            if lease_id:
                                try:
                                    await asyncio.to_thread(client.release_lease, artifact_id, lease_id)
                                except Exception:
                                    pass
                    else:
                        legacy = self._legacy_artifact_path(session.id, session.filename)
                        if not legacy:
                            raise LayerSourceUnavailableError(
                                "File sumber artifact tidak tersedia untuk Get Info."
                            ) from exc
                        yield legacy
                        return
            yield dest
            return
        path = Path(final_path)
        yield path if path.exists() else None

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

    async def _dispatch(
        self,
        layer: Layer,
        lon: float,
        lat: float,
        authorization: Optional[str] = None,
    ):
        adapter = resolve_adapter(layer)
        async with self._source_context(layer, authorization=authorization) as source_path:
            return await asyncio.to_thread(adapter.query, layer, lon, lat, source_path)

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

    # Thin delegates kept for the existing test API (tests/test_wms_feature_info.py);
    # query logic lives in the adapters.
    def _query_wms(self, layer, lon, lat):
        return WmsAdapter().query(layer, lon, lat).response

    def _query_wmts(self, layer, lon, lat):
        return WmtsAdapter().query(layer, lon, lat).response

    def _query_wfs(self, layer, lon, lat):
        return WfsAdapter().query(layer, lon, lat).response

    def _query_esri_mapserver(self, layer, lon, lat):
        return EsriMapserverAdapter().query(layer, lon, lat).response

    def _query_esri_imageserver(self, layer, lon, lat):
        return EsriImageserverAdapter().query(layer, lon, lat).response
