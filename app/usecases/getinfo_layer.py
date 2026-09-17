import asyncio
import os
import requests  # kept for tests/test_wms_feature_info.py monkeypatch target
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from app.core.exceptions import LayerSourceUnavailableError
from app.domain.models import Layer
from app.domain.ports import (
    LahatKodefikasiPort,
    LayerRepositoryPort,
    UploadArtifactClientPort,
    UploadSessionRepositoryPort,
)
from app.domain.schemas import FeatureQueryResponse
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

    def __init__(
        self,
        layer_repo: LayerRepositoryPort,
        session_repo: UploadSessionRepositoryPort,
        artifact_client: Optional[UploadArtifactClientPort] = None,
        kodefikasi_client: Optional[LahatKodefikasiPort] = None,
    ):
        self.layer_repo = layer_repo
        self.session_repo = session_repo
        self.artifact_client = artifact_client
        self.kodefikasi_client = kodefikasi_client

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
        # Enrich kodefikasi (ORDE/KODKWS/JNSRPR) secara additive sebelum field filtering
        response = await self._enrich_kodefikasi(layer, response)
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
                client = self.artifact_client
                if client is None:
                    raise LayerSourceUnavailableError("Adapter sumber artifact tidak dikonfigurasi.")
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

    async def _enrich_kodefikasi(self, layer: Layer, response: FeatureQueryResponse) -> FeatureQueryResponse:
        """Enrich vector features dengan label kodefikasi dari lahat_api.

        Additive: KODE → KODE_label, KODE_description, + _enrichment metadata.
        Degraded (timeout/401/error) → return raw + _enrichment status degraded.
        """
        if response.type != "vector" or not response.features:
            return response
        cfg = (layer.file_metadata or {}).get("kodefikasi")
        if not cfg or not isinstance(cfg, dict):
            return response
        # support legacy key "code_field" and new "enrich_fields"
        code_field = cfg.get("code_field")
        catalog_code = cfg.get("catalog_code")
        plan_component = cfg.get("plan_component") or "PR"
        enrich_fields = cfg.get("enrich_fields") or []
        if not catalog_code or (not code_field and not enrich_fields):
            return response
        # collect distinct codes from all target fields
        fields = []
        if code_field:
            fields.append(code_field)
        for f in enrich_fields:
            if f and f not in fields:
                fields.append(f)
        # also auto-detect: if enrich_fields empty, use code_field only; else combine
        codes_set: set[str] = set()
        for feat in response.features:
            for fld in fields:
                val = feat.get(fld)
                if val is not None and str(val).strip():
                    codes_set.add(str(val).strip())
        if not codes_set:
            return response
        if not self.kodefikasi_client:
            # no client configured → degraded but not fatal
            enriched = []
            for feat in response.features:
                nf = dict(feat)
                for fld in fields:
                    nf[f"{fld}_label"] = None
                nf["_enrichment"] = {"status": "degraded", "reason": "kodefikasi client not configured", "catalog": catalog_code, "component": plan_component}
                enriched.append(nf)
            return FeatureQueryResponse(type="vector", count=len(enriched), features=enriched)

        mapping = await self.kodefikasi_client.resolve(catalog_code, plan_component, list(codes_set))
        # mapping is {} when lahan_api returned not_found (ok) or when degraded (timeout/500).
        # For phase 1, treat missing codes as unknown_code; degraded only when client is None
        # or resolve explicitly returned None. The client currently returns {} for both,
        # so we treat empty-missing as unknown_code to avoid false degraded badges.
        enriched: list[dict] = []
        for feat in response.features:
            nf = dict(feat)
            per_feat_resolved = 0
            for fld in fields:
                raw = feat.get(fld)
                if raw is None or not str(raw).strip():
                    continue
                code = str(raw).strip()
                item = mapping.get(code) if mapping else None
                if item:
                    nf[f"{fld}_label"] = item.get("name")
                    if item.get("description"):
                        nf[f"{fld}_description"] = item.get("description")
                    if item.get("area_code"):
                        nf[f"{fld}_area_code"] = item.get("area_code")
                    per_feat_resolved += 1
                else:
                    nf[f"{fld}_label"] = None
            if per_feat_resolved > 0:
                nf["_enrichment"] = {"status": "ok", "catalog": catalog_code, "component": plan_component}
            elif any(f in feat for f in fields):
                nf["_enrichment"] = {"status": "unknown_code", "catalog": catalog_code, "component": plan_component}
            enriched.append(nf)
        return FeatureQueryResponse(type="vector", count=len(enriched), features=enriched)

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
