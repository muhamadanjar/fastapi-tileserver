"""Public browser-owned workspace and independently authorized admin configuration."""
from typing import Literal

import requests
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from app.application.reference_analysis import ReferenceAnalysis, AnalysisError, owner_hash
from app.core.config import settings
from app.domain.models import AnalysisReference, Layer
from app.infrastructure.db.connection import get_sync_session
from app.infrastructure.wiring import default_analysis_reference_source, default_analysis_storage

router = APIRouter()


def require_admin(request: Request, authorization: str | None = Header(default=None)):
    """Use the global authorization decision, with a standalone-router fallback."""
    if settings.AUTH_DISABLED:
        return
    if hasattr(request.state, "principal"):
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Login dengan izin tiles.manage diperlukan.")
    try:
        response = requests.post(f"{settings.USERMANAGEMENT_API_URL.rstrip('/')}/auth/authorize", headers={"Authorization": authorization}, json={"permission": "tiles.manage"}, timeout=settings.AUTHORIZATION_TIMEOUT_SECONDS)
        if response.status_code == 401:
            raise HTTPException(401, "Sesi login tidak valid.")
        if response.status_code != 200:
            raise HTTPException(503, "Layanan otorisasi tidak tersedia.")
        if response.json()["data"]["allowed"] is not True:
            raise HTTPException(403, "Izin tiles.manage diperlukan.")
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, "Layanan otorisasi tidak tersedia.") from exc


def owner(x_analysis_session: str | None = Header(default=None)):
    try:
        return owner_hash(x_analysis_session)
    except AnalysisError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


def service(session=Depends(get_sync_session)):
    def enqueue(identity, task_id):
        from app.workers.reference_analysis_tasks import run_reference_analysis
        run_reference_analysis.apply_async(args=[identity], task_id=task_id)
    yield ReferenceAnalysis(
        session,
        settings,
        enqueue,
        source=default_analysis_reference_source(),
        storage=default_analysis_storage(),
    )


def invoke(fn, *args):
    try:
        return fn(*args)
    except AnalysisError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class ReferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    category_field: str = Field(min_length=1, max_length=200)
    attributes: list[str] = Field(default_factory=list, max_length=100)


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_id: str = Field(min_length=1, max_length=64)
    reference_id: str = Field(min_length=1, max_length=200)
    operation: Literal["intersect", "clip", "difference", "spatial_join"] = "intersect"


@router.get("/analysis-references/{layer_id}", dependencies=[Depends(require_admin)])
def reference_config(layer_id: str, svc=Depends(service)):
    layer = svc.session.get(Layer, layer_id)
    if layer is None:
        raise HTTPException(404, "Layer tidak ditemukan.")
    ref = svc.session.get(AnalysisReference, layer_id)
    config = ref.model_dump(mode="json") if ref else None
    try:
        frame, _ = svc._source.load_reference(svc.session, layer, settings)
    except Exception as exc:
        # Admin must still be able to detach a broken/missing reference source.
        message = str(exc) if isinstance(exc, ValueError) else "Geometri sumber tidak dapat dibaca. Periksa berkas sumber layer."
        return {"config": config, "fields": [], "source_error": message}
    return {"config": config, "fields": [str(c) for c in frame.columns if c != frame.geometry.name], "source_error": None}


@router.put("/analysis-references/{layer_id}", dependencies=[Depends(require_admin)])
def configure_reference(layer_id: str, body: ReferenceConfig, svc=Depends(service)):
    return invoke(svc.configure, layer_id, body.model_dump())


@router.delete("/analysis-references/{layer_id}", dependencies=[Depends(require_admin)])
def remove_reference(layer_id: str, svc=Depends(service)):
    invoke(svc.remove_reference, layer_id)
    return {"message": "Konfigurasi acuan dilepas. Layer sumber tetap tersedia."}


@router.get("/analysis-workspace/references")
def references(svc=Depends(service)):
    return {"references": svc.references(), "limits": {"features": settings.ANALYSIS_MAX_FEATURES, "upload_bytes": settings.ANALYSIS_MAX_UPLOAD_BYTES}}


@router.post("/analysis-workspace/inputs", status_code=201)
def upload_input(file: UploadFile = File(...), identity=Depends(owner), svc=Depends(service)):
    return invoke(svc.upload, file, identity)


@router.delete("/analysis-workspace/inputs/{input_id}")
def remove_input(input_id: str, identity=Depends(owner), svc=Depends(service)):
    invoke(svc.remove_upload, input_id, identity)
    return {"message": "Unggahan dan hasil dihapus."}


@router.post("/analysis-workspace/jobs", status_code=202)
def start_job(body: StartRequest, identity=Depends(owner), svc=Depends(service)):
    return invoke(svc.start, body.input_id, body.reference_id, identity, body.operation)


@router.get("/analysis-workspace/jobs")
def list_jobs(identity=Depends(owner), svc=Depends(service)):
    return {"jobs": svc.list_jobs(identity)}


@router.get("/analysis-workspace/jobs/{job_id}")
def status(job_id: str, identity=Depends(owner), svc=Depends(service)):
    return invoke(svc.job, job_id, identity)


@router.get("/analysis-workspace/jobs/{job_id}/rows")
def rows(job_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500), identity=Depends(owner), svc=Depends(service)):
    return invoke(svc.rows, job_id, identity, offset, limit)

@router.post("/analysis-workspace/jobs/{job_id}/save", dependencies=[Depends(require_admin)])
def save_job(job_id: str, identity=Depends(owner), svc=Depends(service)):
    return invoke(svc.save, job_id, identity)


@router.get("/analysis-workspace/jobs/{job_id}/download")
def download(job_id: str, format: Literal["geojson", "csv", "shp"] = "geojson", identity=Depends(owner), svc=Depends(service)):
    directory = invoke(svc.result, job_id, identity)
    filename = {"geojson": "result.geojson", "csv": "csv.zip", "shp": "shp.zip"}[format]
    return FileResponse(directory / filename, filename=f"analysis-{job_id}-{filename}", headers={"Cache-Control": "private, no-store"})
