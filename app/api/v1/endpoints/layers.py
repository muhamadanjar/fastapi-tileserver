from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
import geopandas as gpd
import rasterio
from shapely.geometry import Point

from app.domain.schemas import LayerResponse, FeatureQueryResponse
from app.infrastructure.db.connection import get_async_session
from app.infrastructure.db.repository import LayerRepository, UploadSessionRepository

router = APIRouter(prefix="/layers", tags=["layers"])


def _get_layer_repo(session=Depends(get_async_session)) -> LayerRepository:
    return LayerRepository(session)


def _get_session_repo(session=Depends(get_async_session)) -> UploadSessionRepository:
    return UploadSessionRepository(session)


@router.get("", response_model=list[LayerResponse])
async def list_layers(repo: LayerRepository = Depends(_get_layer_repo)):
    layers = await repo.list_all()
    return layers


@router.get("/{layer_id}", response_model=LayerResponse)
async def get_layer(
    layer_id: str,
    repo: LayerRepository = Depends(_get_layer_repo),
):
    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")
    return layer


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
