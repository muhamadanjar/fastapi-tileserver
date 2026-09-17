from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.core.exceptions import LayerNotFoundError, LayerSourceUnavailableError
from app.domain.schemas import GlobalGeocodeResponse
from app.infrastructure.db.connection import get_async_session
from app.infrastructure.db.repository import FeatureRepository, LayerRepository, UploadSessionRepository
from app.infrastructure.wiring import default_nominatim_client
from app.infrastructure.services.upload_artifact_client import UploadArtifactClient
from app.usecases.geocoding import GeocodingUseCase, LayerNotGeocodableError

router = APIRouter(prefix="/geocoding", tags=["geocoding"])


def _get_layer_repo(session=Depends(get_async_session)) -> LayerRepository:
    return LayerRepository(session)


def _get_session_repo(session=Depends(get_async_session)) -> UploadSessionRepository:
    return UploadSessionRepository(session)


def _get_feature_repo(session=Depends(get_async_session)) -> FeatureRepository:
    return FeatureRepository(session)


@router.get("", response_model=GlobalGeocodeResponse)
async def global_geocoding(
    text: str = Query(..., description="Free-form place/address search text"),
    radius: float = Query(default=500, gt=0, le=50_000, description="Search radius in meters around the geocoded point"),
    limit: int = Query(default=5, ge=1, le=50, description="Max nearby features per layer"),
    authorization: Optional[str] = Header(default=None),
    layer_repo: LayerRepository = Depends(_get_layer_repo),
    session_repo: UploadSessionRepository = Depends(_get_session_repo),
    feature_repo: FeatureRepository = Depends(_get_feature_repo),
):
    usecase = GeocodingUseCase(layer_repo, session_repo, feature_repo, nominatim=default_nominatim_client(), artifact_client=UploadArtifactClient())
    try:
        return await usecase.forward_global(text, radius_m=radius, limit=limit, authorization=authorization)
    except LayerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    except LayerNotGeocodableError as exc:
        raise HTTPException(status_code=422, detail=exc.message)
    except LayerSourceUnavailableError as exc:
        raise HTTPException(status_code=424, detail=exc.message)
