from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
import geopandas as gpd
import rasterio
from shapely.geometry import Point
import uuid

from app.domain.schemas import LayerResponse, FeatureQueryResponse, ExternalLayerRequest
from app.domain.models import Layer, JobStatus
from app.infrastructure.db.connection import get_async_session
from app.infrastructure.db.repository import LayerRepository, UploadSessionRepository
from app.core.utils import slugify

router = APIRouter(prefix="/layers", tags=["layers"])


def _get_layer_repo(session=Depends(get_async_session)) -> LayerRepository:
    return LayerRepository(session)


def _get_session_repo(session=Depends(get_async_session)) -> UploadSessionRepository:
    return UploadSessionRepository(session)


@router.get("", response_model=list[LayerResponse])
async def list_layers(repo: LayerRepository = Depends(_get_layer_repo)):
    layers = await repo.list_all()
    responses = []
    for layer in layers:
        responses.append(LayerResponse(
            id=layer.id,
            upload_session_id=layer.upload_session_id,
            layer_type=layer.layer_type,
            filename=layer.filename,
            file_type=layer.file_type,
            tile_url_template=layer.tile_url_template,
            status="done" if not layer.upload_session_id else "pending",
            created_at=layer.created_at,
            bbox=[layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north] if all([layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north]) else None,
            file_metadata=layer.file_metadata,
        ))
    return responses


@router.get("/{layer_id}", response_model=LayerResponse)
async def get_layer(
    layer_id: str,
    repo: LayerRepository = Depends(_get_layer_repo),
):
    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")
    return LayerResponse(
        id=layer.id,
        upload_session_id=layer.upload_session_id,
        layer_type=layer.layer_type,
        filename=layer.filename,
        file_type=layer.file_type,
        tile_url_template=layer.tile_url_template,
        status="done" if not layer.upload_session_id else "pending",
        created_at=layer.created_at,
        bbox=[layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north] if all([layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north]) else None,
        file_metadata=layer.file_metadata,
    )


@router.post("/external", response_model=LayerResponse)
async def add_external_layer(
    req: ExternalLayerRequest,
    repo: LayerRepository = Depends(_get_layer_repo),
):
    layer = Layer(
        id=str(uuid.uuid4()),
        code=slugify(req.filename),
        filename=req.filename,
        file_type="external",
        layer_type=req.layer_type,
        tile_url_template=req.source_url,
        file_metadata=req.params or {},
        upload_session_id=None,
        is_visible=True,
    )
    created = await repo.create(layer)
    return LayerResponse(
        id=created.id,
        upload_session_id=created.upload_session_id,
        layer_type=created.layer_type,
        filename=created.filename,
        file_type=created.file_type,
        tile_url_template=created.tile_url_template,
        status="done",
        created_at=created.created_at,
        file_metadata=created.file_metadata,
    )


@router.delete("/{layer_id}")
async def delete_layer(
    layer_id: str,
    repo: LayerRepository = Depends(_get_layer_repo),
):
    deleted = await repo.delete(layer_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")
    return {"message": "Layer deleted successfully"}


def _query_vector(source_path: Path, lon: float, lat: float) -> FeatureQueryResponse:
    gdf = gpd.read_file(source_path)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    point = Point(lon, lat)
    matching = gdf[gdf.geometry.contains(point)]

    features = []
    for _, row in matching.iterrows():
        props = row.drop(labels=['geometry']).to_dict()
        cleaned = {
            k: (v if isinstance(v, (str, int, float, bool, type(None))) else str(v))
            for k, v in props.items()
        }
        features.append(cleaned)

    return FeatureQueryResponse(type='vector', count=len(features), features=features)


def _query_raster(source_path: Path, lon: float, lat: float) -> FeatureQueryResponse:
    with rasterio.open(source_path) as src:
        row, col = src.index(lon, lat)
        if row < 0 or col < 0 or row >= src.height or col >= src.width:
            return FeatureQueryResponse(type='raster', count=0, values={})

        sample = list(src.sample([(lon, lat)]))[0]
        values = {f'band_{i+1}': float(val) for i, val in enumerate(sample)}

    return FeatureQueryResponse(type='raster', count=1, values=values)


@router.get("/{layer_id}/features", response_model=FeatureQueryResponse)
async def query_features(
    layer_id: str,
    lon: float,
    lat: float,
    layer_repo: LayerRepository = Depends(_get_layer_repo),
    session_repo: UploadSessionRepository = Depends(_get_session_repo),
):
    layer = await layer_repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")

    upload_session = await session_repo.get_by_id(layer.upload_session_id)
    if not upload_session or not upload_session.final_path:
        raise HTTPException(status_code=404, detail="Source file not found.")

    source_path = Path(upload_session.final_path)
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Source file missing on disk.")

    if layer.file_type == 'vector':
        return _query_vector(source_path, lon, lat)
    else:
        return _query_raster(source_path, lon, lat)
