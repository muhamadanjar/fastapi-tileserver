"""
Overlay Analysis endpoints.

Provides spatial overlay operations on vector layers.
"""

import logging
from pathlib import Path
from typing import Iterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.core.config import Settings
from app.domain.models import Feature, Layer
from app.domain.schemas import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisSaveResponse,
    AnalysisStatusResponse,
    ValidateAnalysisResponse,
)
from app.infrastructure.db.connection import get_sync_session
from app.infrastructure.db.repository import (
    SyncAnalysisResultRepository,
    SyncLayerRepository,
    SyncUploadSessionRepository,
)
from app.infrastructure.services.analysis_export import AnalysisExportService
from app.infrastructure.services.analysis_task import CeleryAnalysisTaskEnqueuer
from app.usecases.overlay_analysis import OverlayAnalysisUseCase

logger = logging.getLogger(__name__)
router = APIRouter()
settings = Settings()


def _build_usecase(session: Session) -> OverlayAnalysisUseCase:
    """Build usecase bound to a sync session."""

    def _get_features(project_id: str) -> list[Feature]:
        return list(
            session.exec(select(Feature).where(Feature.project_id == project_id)).all()
        )

    return OverlayAnalysisUseCase(
        layer_repo=SyncLayerRepository(session),
        analysis_repo=SyncAnalysisResultRepository(session),
        upload_repo=SyncUploadSessionRepository(session),
        get_project_features_fn=_get_features,
        export_service=AnalysisExportService(settings.UPLOAD_DIR),
        task_enqueuer=CeleryAnalysisTaskEnqueuer(),
        ephemeral_ttl_hours=settings.ANALYSIS_EPHEMERAL_TTL_HOURS,
    )


def get_analysis_usecase(
    session: Session = Depends(get_sync_session),
) -> Iterator[OverlayAnalysisUseCase]:
    """FastAPI dependency: usecase with repos injected for request lifetime."""
    yield _build_usecase(session)


@router.get("/operations")
def list_operations(uc: OverlayAnalysisUseCase = Depends(get_analysis_usecase)):
    """List all available overlay operations with metadata."""
    return {"operations": uc.get_available_operations()}


@router.get("/layers")
def list_analysis_layers(uc: OverlayAnalysisUseCase = Depends(get_analysis_usecase)):
    """List layers available as input for analysis."""
    return {"layers": uc.get_layer_sources()}


@router.post("/validate", response_model=ValidateAnalysisResponse)
def validate_overlay(
    request: AnalysisRequest,
    uc: OverlayAnalysisUseCase = Depends(get_analysis_usecase),
):
    """Validate if analysis is possible with given inputs."""
    result = uc.validate_analysis(
        operation=request.operation,
        layer_a_id=request.input_layer_a_id,
        layer_b_id=request.input_layer_b_id,
    )
    return ValidateAnalysisResponse(**result)


@router.post("/run", response_model=AnalysisResponse)
def run_overlay_analysis(
    request: AnalysisRequest,
    uc: OverlayAnalysisUseCase = Depends(get_analysis_usecase),
):
    """Execute overlay analysis. Sync by default; async when async_run=true."""
    try:
        if request.async_run:
            result = uc.start_analysis_async(request.model_dump())
            return AnalysisResponse(
                result_layer_id=result["result_layer_id"],
                operation=request.operation,
                feature_count=0,
                bbox=None,
                geojson_url="",
                async_task_id=result["async_task_id"],
            )
        result = uc.run_analysis(request.model_dump())
        return AnalysisResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("Analysis failed")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.delete("/cleanup")
def cleanup_results(
    ttl_hours: Optional[int] = Query(None, description="TTL override in hours"),
    uc: OverlayAnalysisUseCase = Depends(get_analysis_usecase),
):
    """Delete abandoned ephemeral analysis results older than TTL."""
    return uc.cleanup_ephemeral(ttl_hours=ttl_hours)


@router.get("/status/{result_id}", response_model=AnalysisStatusResponse)
def analysis_status(
    result_id: str,
    uc: OverlayAnalysisUseCase = Depends(get_analysis_usecase),
):
    """Poll status of an analysis run (useful for async runs)."""
    status = uc.get_analysis_status(result_id)
    if not status:
        raise HTTPException(status_code=404, detail="Analysis result not found")
    return AnalysisStatusResponse(**status)


@router.get("/{result_layer_id}/preview")
def preview_result(
    result_layer_id: str,
    session: Session = Depends(get_sync_session),
):
    """Preview analysis result as GeoJSON."""
    layer = session.exec(select(Layer).where(Layer.id == result_layer_id)).first()
    if not layer:
        raise HTTPException(status_code=404, detail="Result not found")

    if layer.tile_url_template and layer.tile_url_template.startswith("/data/"):
        file_path = layer.tile_url_template.lstrip("/")
        if Path(file_path).exists():
            return FileResponse(
                path=file_path,
                media_type="application/geo+json",
                filename=f"{layer.filename}.geojson",
            )

    raise HTTPException(status_code=404, detail="Result file not found")


@router.post("/{result_layer_id}/save", response_model=AnalysisSaveResponse)
def save_result(
    result_layer_id: str,
    uc: OverlayAnalysisUseCase = Depends(get_analysis_usecase),
):
    """Save ephemeral analysis result as permanent layer."""
    try:
        result = uc.save_analysis_result(result_layer_id)
        return AnalysisSaveResponse(
            result_layer_id=result_layer_id,
            layer_id=result_layer_id,
            message=result["message"],
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{result_layer_id}")
def discard_result(
    result_layer_id: str,
    uc: OverlayAnalysisUseCase = Depends(get_analysis_usecase),
):
    """Discard ephemeral analysis result."""
    try:
        result = uc.delete_analysis_result(result_layer_id)
        return {"message": result["message"]}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{result_layer_id}/download")
def download_result(
    result_layer_id: str,
    format: str = Query("geojson", description="Export format: geojson or shp"),
    session: Session = Depends(get_sync_session),
):
    """Download analysis result in specified format."""
    export_svc = AnalysisExportService(settings.UPLOAD_DIR)
    result = SyncAnalysisResultRepository(session).get_by_layer_id(result_layer_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    if not result.result_file_path:
        raise HTTPException(status_code=404, detail="Result file not found")

    if format == "shp":
        zip_path = export_svc.export_shp_zip(result.result_file_path)
        if not zip_path:
            raise HTTPException(status_code=404, detail="Result file not found")
        return FileResponse(
            path=str(zip_path),
            media_type="application/zip",
            filename=f"{result.output_name or result.operation}_result.zip",
        )
    else:
        geojson_path = export_svc.get_geojson_path(result.result_file_path)
        if not geojson_path:
            raise HTTPException(status_code=404, detail="Result file not found")
        return FileResponse(
            path=str(geojson_path),
            media_type="application/geo+json",
            filename=f"{result.output_name or result.operation}_result.geojson",
        )