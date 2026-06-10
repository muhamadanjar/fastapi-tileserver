import asyncio
import os
import shutil
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
import uuid

from app.domain.schemas import LayerResponse, FeatureQueryResponse, ExternalLayerRequest, PatchLayerRequest, LayerFieldsResponse
from app.domain.models import Layer, JobStatus
from app.infrastructure.db.connection import get_async_session
from app.infrastructure.db.repository import LayerRepository, UploadSessionRepository
from app.infrastructure.services.csw_sync import sync_layer, delete_layer_from_csw
from app.core.utils import slugify, generate_unique_code
from app.core.response import APIResponse
from app.core.config import settings
from app.workers.tasks import process_tiling_task
from app.core.exceptions import LayerFieldsUnavailableError, LayerNotFoundError
from app.usecases.getinfo_layer import QueryLayerFeaturesUseCase
from app.usecases.get_layer_fields import GetLayerFieldsUseCase

router = APIRouter(prefix="/layers", tags=["layers"])


def _get_layer_repo(session=Depends(get_async_session)) -> LayerRepository:
    return LayerRepository(session)


def _get_session_repo(session=Depends(get_async_session)) -> UploadSessionRepository:
    return UploadSessionRepository(session)


@router.get("")
async def list_layers(
    skip: int = 0,
    take: int = 10,
    page: Optional[int] = None,
    search: Optional[str] = None,
    sort: Optional[str] = None,
    dir: Optional[str] = None,
    repo: LayerRepository = Depends(_get_layer_repo),
    session_repo: UploadSessionRepository = Depends(_get_session_repo),
):
    # Calculate skip based on page if provided
    if page and page > 1:
        skip = (page - 1) * take

    # Get paginated layers with optional search, sort, and direction
    result = await repo.paginate(
        skip=skip,
        limit=take,
        search=search,
        sort_field=sort,
        sort_dir=dir or "asc"
    )
    layers = result["data"]
    metas = result["metas"]

    responses = []
    for layer in layers:
        status = "done"
        if layer.upload_session_id:
            upload_session = await session_repo.get_by_id(layer.upload_session_id)
            if upload_session:
                status = upload_session.status

        responses.append(LayerResponse(
            id=layer.id,
            upload_session_id=layer.upload_session_id,
            code=layer.code,
            layer_type=layer.layer_type,
            filename=layer.filename,
            file_type=layer.file_type,
            tile_url_template=layer.tile_url_template,
            status=status,
            created_at=layer.created_at,
            bbox=[layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north] if all([layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north]) else None,
            file_metadata=layer.file_metadata,
        ))

    return APIResponse.success(
        message="List layers with pagination",
        data=responses,
        metas=metas
    )


@router.get("/{layer_id}", response_model=LayerResponse)
async def get_layer(
    layer_id: str,
    repo: LayerRepository = Depends(_get_layer_repo),
    session_repo: UploadSessionRepository = Depends(_get_session_repo),
):
    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")

    status = "done"
    if layer.upload_session_id:
        upload_session = await session_repo.get_by_id(layer.upload_session_id)
        if upload_session:
            status = upload_session.status

    return LayerResponse(
        id=layer.id,
        upload_session_id=layer.upload_session_id,
        code=layer.code,
        layer_type=layer.layer_type,
        filename=layer.filename,
        file_type=layer.file_type,
        tile_url_template=layer.tile_url_template,
        status=status,
        created_at=layer.created_at,
        bbox=[layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north] if all([layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north]) else None,
        file_metadata=layer.file_metadata,
    )


@router.patch("/{layer_id}", response_model=LayerResponse)
async def patch_layer(
    layer_id: str,
    req: PatchLayerRequest,
    repo: LayerRepository = Depends(_get_layer_repo),
    session_repo: UploadSessionRepository = Depends(_get_session_repo),
):
    from app.infrastructure.services.bbox_extractor import extract_bbox

    updated = await repo.update(
        layer_id,
        file_metadata=req.file_metadata,
        filename=req.filename,
        layer_type=req.layer_type,
        tile_url_template=req.tile_url_template,
        abstract=req.abstract,
        topic_category=req.topic_category,
        language=req.language,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")

    # Refresh bbox jika flag active dan layer adalah external
    if req.refresh_bbox and updated.file_type == "external" and updated.layer_type in ("wms", "wmts", "esri_mapserver", "esri_featureserver", "esri_imageserver", "esri_tileserver", "esri_vectortileserver"):
        bbox_result = await asyncio.to_thread(extract_bbox, updated.layer_type, updated.tile_url_template, updated.file_metadata)
        if bbox_result:
            updated = await repo.update(
                layer_id,
                bbox_west=bbox_result[0],
                bbox_south=bbox_result[1],
                bbox_east=bbox_result[2],
                bbox_north=bbox_result[3],
            )

    status = "done"
    if updated.upload_session_id:
        upload_session = await session_repo.get_by_id(updated.upload_session_id)
        if upload_session:
            status = upload_session.status

    await asyncio.to_thread(sync_layer, updated)
    return LayerResponse(
        id=updated.id,
        upload_session_id=updated.upload_session_id,
        code=updated.code,
        layer_type=updated.layer_type,
        filename=updated.filename,
        file_type=updated.file_type,
        tile_url_template=updated.tile_url_template,
        status=status,
        created_at=updated.created_at,
        bbox=[updated.bbox_west, updated.bbox_south, updated.bbox_east, updated.bbox_north] if all([updated.bbox_west, updated.bbox_south, updated.bbox_east, updated.bbox_north]) else None,
        file_metadata=updated.file_metadata,
        abstract=updated.abstract,
        topic_category=updated.topic_category,
        language=updated.language,
    )


@router.post("/{layer_id}/sync-bbox")
async def sync_layer_bbox(
    layer_id: str,
    repo: LayerRepository = Depends(_get_layer_repo),
    upload_repo: UploadSessionRepository = Depends(_get_session_repo),
):
    from app.infrastructure.services.bbox_extractor import extract_bbox, extract_bbox_from_file, get_crs_from_file
    import os

    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")

    bbox = None
    crs_str = None

    FILE_BASED_TYPES = {'tile', 'mvt', 'vector'}
    EXTERNAL_TYPES = {'wms', 'wmts', 'wfs', 'geojson', 'kml',
                      'esri_mapserver', 'esri_featureserver', 'esri_tileserver',
                      'esri_vectortileserver', 'esri_imageserver'}

    if layer.layer_type in FILE_BASED_TYPES:
        if not layer.upload_session_id:
            raise HTTPException(status_code=422, detail="No source file: layer has no upload session")
        session = await upload_repo.get_by_id(layer.upload_session_id)
        if not session or not session.final_path:
            raise HTTPException(status_code=422, detail="Source file path not found in upload session")
        if not os.path.exists(session.final_path):
            raise HTTPException(status_code=422, detail="Source file no longer exists on disk")
        bbox = await asyncio.to_thread(extract_bbox_from_file, session.final_path)
        if bbox:
            crs_str = await asyncio.to_thread(get_crs_from_file, session.final_path)

    elif layer.layer_type in EXTERNAL_TYPES:
        params = dict(layer.file_metadata or {}) if layer.file_metadata else {}
        if layer.layer_type == 'wms' and not params.get('layers'):
            if 'geoserver' in params and params['geoserver'].get('layer_name'):
                params['layers'] = params['geoserver']['layer_name']
        bbox = await asyncio.to_thread(extract_bbox, layer.layer_type, layer.tile_url_template, params)

    if not bbox:
        raise HTTPException(status_code=422, detail="Could not extract bbox for this layer")

    west, south, east, north = bbox
    new_metadata = dict(layer.file_metadata or {})
    if crs_str:
        new_metadata['crs'] = crs_str

    await repo.update(
        layer_id=layer_id,
        bbox_west=west,
        bbox_south=south,
        bbox_east=east,
        bbox_north=north,
        file_metadata=new_metadata,
    )

    return {
        "message": "BBox synced",
        "layer_id": layer_id,
        "bbox": [west, south, east, north],
        "crs": crs_str,
    }


@router.post("/{layer_id}/retile")
async def retile_layer(
    layer_id: str,
    repo: LayerRepository = Depends(_get_layer_repo),
    session_repo: UploadSessionRepository = Depends(_get_session_repo),
):
    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found")
    if not layer.upload_session_id:
        raise HTTPException(status_code=422, detail="External layers cannot be retiled")

    upload_session = await session_repo.get_by_id(layer.upload_session_id)
    if not upload_session or not upload_session.final_path:
        raise HTTPException(status_code=404, detail="Source file not found")
    if not Path(upload_session.final_path).exists():
        raise HTTPException(status_code=404, detail="Source file missing from disk")

    output_format = "mvt" if layer.layer_type == "mvt" else "raster"
    process_tiling_task.delay(
        upload_session.id, layer.id,
        layer.file_type, upload_session.final_path, output_format
    )
    return {"message": "Retiling queued", "upload_id": upload_session.id}


@router.post("/external", response_model=LayerResponse)
async def add_external_layer(
    req: ExternalLayerRequest,
    repo: LayerRepository = Depends(_get_layer_repo),
):
    from app.infrastructure.services.bbox_extractor import extract_bbox

    # Fetch bbox dari remote service (jika tidak override di request)
    bbox_result = None
    if req.bbox and len(req.bbox) == 4:
        bbox_result = tuple(req.bbox)
    else:
        bbox_result = await asyncio.to_thread(extract_bbox, req.layer_type, req.source_url, req.params)

    filename_without_ext = Path(req.filename).stem
    base_code = slugify(filename_without_ext)
    unique_code = await generate_unique_code(base_code, repo.code_exists)

    layer = Layer(
        id=str(uuid.uuid4()),
        code=unique_code,
        filename=req.filename,
        file_type="external",
        layer_type=req.layer_type,
        tile_url_template=req.source_url,
        file_metadata=req.params or {},
        upload_session_id=None,
        is_visible=True,
        bbox_west=bbox_result[0] if bbox_result else None,
        bbox_south=bbox_result[1] if bbox_result else None,
        bbox_east=bbox_result[2] if bbox_result else None,
        bbox_north=bbox_result[3] if bbox_result else None,
    )
    created = await repo.create(layer)
    await asyncio.to_thread(sync_layer, created)
    return LayerResponse(
        id=created.id,
        upload_session_id=created.upload_session_id,
        code=created.code,
        layer_type=created.layer_type,
        filename=created.filename,
        file_type=created.file_type,
        tile_url_template=created.tile_url_template,
        status="done",
        created_at=created.created_at,
        bbox=[created.bbox_west, created.bbox_south, created.bbox_east, created.bbox_north]
            if all([created.bbox_west, created.bbox_south, created.bbox_east, created.bbox_north])
            else None,
        file_metadata=created.file_metadata,
        abstract=created.abstract,
        topic_category=created.topic_category,
        language=created.language,
    )


def _fmt_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


@router.get("/{layer_id}/delete-preview")
async def get_delete_preview(
    layer_id: str,
    layer_repo: LayerRepository = Depends(_get_layer_repo),
    session_repo: UploadSessionRepository = Depends(_get_session_repo),
):
    layer = await layer_repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")

    items = []

    # DB record — always present
    items.append({"type": "db_record", "label": "Layer record", "detail": layer.filename})

    # Tile files on disk
    tile_dir = Path(settings.TILES_DIR) / layer_id
    if tile_dir.exists():
        try:
            size = sum(f.stat().st_size for f in tile_dir.rglob('*') if f.is_file())
            items.append({"type": "tile_files", "label": "Tile files", "detail": _fmt_size(size)})
        except OSError:
            pass

    # Source file from UploadSession
    if layer.upload_session_id:
        session = await session_repo.get_by_id(layer.upload_session_id)
        if session and session.final_path and os.path.exists(session.final_path):
            try:
                size = os.path.getsize(session.final_path)
                items.append({"type": "source_file", "label": "Source file", "detail": f"{session.filename} ({_fmt_size(size)})"})
            except OSError:
                pass

    # CSW record — always present
    items.append({"type": "csw_record", "label": "CSW catalog record", "detail": layer_id})

    return {"layer_id": layer_id, "filename": layer.filename, "items": items}


@router.delete("/{layer_id}")
async def delete_layer(
    layer_id: str,
    layer_repo: LayerRepository = Depends(_get_layer_repo),
    session_repo: UploadSessionRepository = Depends(_get_session_repo),
):
    layer = await layer_repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")

    # Store upload_session_id before deleting layer (FK constraint)
    upload_session_id = layer.upload_session_id
    upload_session = None
    if upload_session_id:
        upload_session = await session_repo.get_by_id(upload_session_id)

    # 1. Delete tile files from disk
    tile_dir = Path(settings.TILES_DIR) / layer_id
    if tile_dir.exists():
        try:
            shutil.rmtree(tile_dir, ignore_errors=True)
        except OSError:
            pass

    # 2. Delete DB row first (removes FK constraint to UploadSession)
    await layer_repo.delete(layer_id)

    # 3. Delete source file + UploadSession
    if upload_session:
        if upload_session.final_path and os.path.exists(upload_session.final_path):
            try:
                os.unlink(upload_session.final_path)
            except OSError:
                pass
        await session_repo.delete(upload_session_id)

    # 4. Delete CSW record
    await asyncio.to_thread(delete_layer_from_csw, layer_id)

    return {"message": "Layer deleted successfully"}


@router.get("/{layer_id}/fields", response_model=LayerFieldsResponse)
async def get_layer_fields(
    layer_id: str,
    layer_repo: LayerRepository = Depends(_get_layer_repo),
    session_repo: UploadSessionRepository = Depends(_get_session_repo),
):
    usecase = GetLayerFieldsUseCase(layer_repo, session_repo)
    try:
        return await usecase.execute(layer_id)
    except (LayerNotFoundError, LayerFieldsUnavailableError) as exc:
        raise HTTPException(status_code=404, detail=exc.message)


@router.get("/{layer_id}/features", response_model=FeatureQueryResponse)
async def query_features(
    layer_id: str,
    lon: float,
    lat: float,
    layer_repo: LayerRepository = Depends(_get_layer_repo),
    session_repo: UploadSessionRepository = Depends(_get_session_repo),
):
    usecase = QueryLayerFeaturesUseCase(layer_repo, session_repo)
    return await usecase.execute(layer_id, lon, lat)
