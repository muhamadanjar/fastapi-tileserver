import asyncio
import os
import shutil
from contextlib import nullcontext
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from fastapi import APIRouter, Depends, Header, HTTPException, Query
import uuid
from defusedxml.ElementTree import fromstring as safe_fromstring, ParseError as SafeParseError

from app.domain.schemas import LayerResponse, FeatureQueryResponse, ExternalLayerRequest, PatchLayerRequest, LayerFieldsResponse, FieldUniqueValuesResponse, BboxFeaturesResponse, EsriDownloadRequest, LayerStyleRequest, LayerStyleResponse, LayerLegendResponse, SyncBBoxRequest
from app.domain.models import Layer, JobStatus
from app.infrastructure.db.connection import db, get_async_session
from app.infrastructure.db.repository import LayerRepository, ProjectRepository, UploadSessionRepository
from app.infrastructure.services.csw_sync import sync_layer, delete_layer_from_csw
from app.infrastructure.services.geoserver_service import GeoServerService, GeoServerStyleError
from app.infrastructure.services.sld_builder import build_sld, ALLOWED_GEOMETRIES
from app.core.utils import slugify, generate_unique_code
from app.core.style_utils import merge_style_state
from app.core.response import APIResponse
from app.core.config import settings
from app.workers.tasks import process_tiling_task, download_esri_layer_task
from app.core.exceptions import LayerFieldsUnavailableError, LayerNotFoundError, LayerSourceUnavailableError
from app.usecases.getinfo_layer import QueryLayerFeaturesUseCase
from app.usecases.get_layer_fields import GetLayerFieldsUseCase
from app.usecases.get_field_unique_values import GetFieldUniqueValuesUseCase
from app.usecases.get_features_in_bbox import GetFeaturesInBboxUseCase
from app.infrastructure.services.upload_artifact_client import UploadArtifactClient

router = APIRouter(prefix="/layers", tags=["layers"])


def _fetch_esri_mapserver_layers(url: str) -> Optional[list]:
    """Fetch list available layers dari ESRI MapServer.

    ESRI MapServer REST API response format:
    {
      "layers": [
        {"id": 0, "name": "Layer 1", ...},
        {"id": 1, "name": "Layer 2", ...},
        ...
      ]
    }
    """
    import requests

    if not url:
        return None

    try:
        resp = requests.get(f'{url}?f=json', timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            layers = data.get('layers') or []
            return [
                {'id': layer.get('id'), 'name': layer.get('name')}
                for layer in layers
                if layer.get('id') is not None and layer.get('name')
            ]
    except Exception:
        pass
    return None


def _fetch_wms_layers(url: str) -> Optional[list]:
    """Discover named WMS layers in a GetCapabilities document."""
    import requests

    if not url:
        return None
    try:
        parsed = urlsplit(url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        params.update({"service": "WMS", "request": "GetCapabilities"})
        capabilities_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        response = requests.get(capabilities_url, params=params, timeout=10)
        if response.status_code != 200:
            return None
        root = safe_fromstring(response.content)
        layers = []
        seen = set()
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != "Layer":
                continue
            children = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in element}
            name = children.get("Name")
            if name and name not in seen:
                seen.add(name)
                layers.append({"id": name, "name": children.get("Title") or name})
        return layers or None
    except (requests.RequestException, SafeParseError, ValueError):
        return None


def _get_layer_repo(session=Depends(get_async_session)) -> LayerRepository:
    return LayerRepository(session)


def _get_session_repo(session=Depends(get_async_session)) -> UploadSessionRepository:
    return UploadSessionRepository(session)


_ESRI_LEGEND_TYPES = {"esri_mapserver", "esri_imageserver"}


def _legend_response(layer: Layer) -> LayerLegendResponse:
    """Return the upstream-native legend location for a layer when available."""
    metadata = layer.file_metadata or {}

    if layer.layer_type == "wms":
        layer_name = (metadata.get("geoserver") or {}).get("layer_name")
        layer_name = layer_name or metadata.get("layers") or metadata.get("layer")
        if not layer_name:
            return LayerLegendResponse(
                layer_id=layer.id,
                layer_type=layer.layer_type,
                available=False,
                detail="WMS layer name is not configured",
            )
        parts = urlsplit(layer.tile_url_template)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update({
            "service": "WMS",
            "request": "GetLegendGraphic",
            "version": "1.3.0",
            "layer": layer_name,
            "format": "image/png",
        })
        return LayerLegendResponse(
            layer_id=layer.id,
            layer_type=layer.layer_type,
            available=True,
            legend_url=urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), "")),
            format="image/png",
        )

    if layer.layer_type in _ESRI_LEGEND_TYPES:
        parts = urlsplit(layer.tile_url_template.rstrip("/"))
        service_name = "MapServer" if layer.layer_type == "esri_mapserver" else "ImageServer"
        marker = f"/{service_name}"
        service_path, separator, _ = parts.path.partition(marker)
        if not parts.scheme or not parts.netloc or not separator:
            return LayerLegendResponse(
                layer_id=layer.id,
                layer_type=layer.layer_type,
                available=False,
                detail=f"Layer does not point to an Esri {service_name} service",
            )
        return LayerLegendResponse(
            layer_id=layer.id,
            layer_type=layer.layer_type,
            available=True,
            legend_url=urlunsplit((parts.scheme, parts.netloc, f"{service_path}{marker}/legend", "f=pjson", "")),
            format="application/json",
        )

    return LayerLegendResponse(
        layer_id=layer.id,
        layer_type=layer.layer_type,
        available=False,
        detail=f"Layer type '{layer.layer_type}' does not expose a server-side legend",
    )


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
            bbox=[layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north] if all(v is not None for v in [layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north]) else None,
            file_metadata=layer.file_metadata,
        ))

    return APIResponse.success(
        message="List layers with pagination",
        data=responses,
        metas=metas
    )


@router.get("/{layer_id}/legend", response_model=LayerLegendResponse)
async def get_layer_legend(
    layer_id: str,
    repo: LayerRepository = Depends(_get_layer_repo),
):
    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")
    return _legend_response(layer)


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
        bbox=[layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north] if all(v is not None for v in [layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north]) else None,
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

    # Get existing layer untuk check layer_type
    existing = await repo.get_by_id(layer_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")

    # Prepare file metadata
    file_metadata = req.file_metadata or {}

    # Determine layer type (use request value or existing value)
    layer_type = req.layer_type or existing.layer_type
    tile_url_update = req.tile_url_template if req.tile_url_template is not None else req.source_url
    tile_url = tile_url_update or existing.tile_url_template

    # Fetch available sublayers untuk services that expose them.
    if layer_type == 'esri_mapserver' and tile_url_update:
        layers_list = await asyncio.to_thread(_fetch_esri_mapserver_layers, tile_url)
        if layers_list:
            file_metadata['availableLayers'] = layers_list
    elif layer_type == 'wms' and tile_url:
        layers_list = await asyncio.to_thread(_fetch_wms_layers, tile_url)
        if layers_list:
            file_metadata['availableLayers'] = layers_list

    updated = await repo.update(
        layer_id,
        file_metadata=file_metadata,
        filename=req.filename,
        layer_type=req.layer_type,
        tile_url_template=tile_url_update,
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
        bbox=[updated.bbox_west, updated.bbox_south, updated.bbox_east, updated.bbox_north] if all(v is not None for v in [updated.bbox_west, updated.bbox_south, updated.bbox_east, updated.bbox_north]) else None,
        file_metadata=updated.file_metadata,
        abstract=updated.abstract,
        topic_category=updated.topic_category,
        language=updated.language,
    )


def _require_geoserver_layer(layer) -> dict:
    """Return geoserver metadata or raise 422 for non-published layers."""
    gs_meta = (layer.file_metadata or {}).get("geoserver")
    if layer.layer_type != "wms" or not gs_meta:
        raise HTTPException(
            status_code=422,
            detail="Style editing is only available for WMS layers published to GeoServer",
        )
    return gs_meta


@router.get("/{layer_id}/style", response_model=LayerStyleResponse)
async def get_layer_style(
    layer_id: str,
    repo: LayerRepository = Depends(_get_layer_repo),
):
    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")
    _require_geoserver_layer(layer)
    return LayerStyleResponse(
        layer_id=layer_id,
        style_name=f"layer_{layer_id}",
        style=(layer.file_metadata or {}).get("style"),
    )


@router.put("/{layer_id}/style", response_model=LayerResponse)
async def put_layer_style(
    layer_id: str,
    req: LayerStyleRequest,
    repo: LayerRepository = Depends(_get_layer_repo),
    session_repo: UploadSessionRepository = Depends(_get_session_repo),
):
    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")
    gs_meta = _require_geoserver_layer(layer)

    style_name = f"layer_{layer_id}"

    if req.mode == "simple":
        if not req.style:
            raise HTTPException(status_code=422, detail="'style' is required when mode=simple")
        unknown = set(req.style) - ALLOWED_GEOMETRIES
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown geometry keys: {sorted(unknown)}. Allowed: {sorted(ALLOWED_GEOMETRIES)}",
            )
        try:
            sld_body = build_sld(req.style, style_name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    else:  # mode == "sld"
        if not req.sld_body:
            raise HTTPException(status_code=422, detail="'sld_body' is required when mode=sld")
        try:
            safe_fromstring(req.sld_body.encode("utf-8"))
        except (SafeParseError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid SLD XML: {exc}")
        sld_body = req.sld_body

    stored_style = merge_style_state(
        (layer.file_metadata or {}).get("style"),
        mode=req.mode,
        style_name=style_name,
        sld_body=sld_body,
        style=req.style,
    )

    svc = GeoServerService(
        url=settings.GEOSERVER_URL,
        username=settings.GEOSERVER_USER,
        password=settings.GEOSERVER_PASSWORD,
        workspace=settings.GEOSERVER_WORKSPACE,
    )
    try:
        await asyncio.to_thread(svc.upsert_style, style_name, sld_body)
        await asyncio.to_thread(svc.set_default_style, gs_meta["layer_name"], style_name)
    except GeoServerStyleError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.detail)

    # Verify the style actually landed as the layer default (guards against
    # silent grey maps when the target layer name is wrong/duplicated).
    default_style_name = await asyncio.to_thread(svc.get_default_style, gs_meta["layer_name"])
    expected = f"{settings.GEOSERVER_WORKSPACE}:{style_name}"
    style_verified = default_style_name == expected

    updated = await repo.update(
        layer_id,
        file_metadata={
            "style": stored_style,
            "geoserver": {**gs_meta, "style_name": style_name},
        },
    )

    status = "done"
    if updated.upload_session_id:
        upload_session = await session_repo.get_by_id(updated.upload_session_id)
        if upload_session:
            status = upload_session.status

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
        bbox=[updated.bbox_west, updated.bbox_south, updated.bbox_east, updated.bbox_north]
        if all([updated.bbox_west, updated.bbox_south, updated.bbox_east, updated.bbox_north])
        else None,
        file_metadata=updated.file_metadata,
        abstract=updated.abstract,
        topic_category=updated.topic_category,
        language=updated.language,
        style_verified=style_verified,
        default_style_name=default_style_name,
    )


@router.post("/{layer_id}/sync-bbox")
async def sync_layer_bbox(
    layer_id: str,
    repo: LayerRepository = Depends(_get_layer_repo),
    upload_repo: UploadSessionRepository = Depends(_get_session_repo),
    req: Optional[SyncBBoxRequest] = None,
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

    if req is not None:
        bbox = tuple(req.bbox)

    elif layer.layer_type in FILE_BASED_TYPES:
        if not layer.upload_session_id:
            raise HTTPException(status_code=422, detail="No source file: layer has no upload session")
        session = await upload_repo.get_by_id(layer.upload_session_id)
        if not session or not session.final_path:
            raise HTTPException(status_code=422, detail="Source file path not found in upload session")
        # Artifact handoff (upload-api): final_path="artifact://<id>", materiakan dulu seperti di tasks.py.
        artifact_id = (
            session.final_path.removeprefix("artifact://")
            if session.final_path.startswith("artifact://")
            else None
        )
        if artifact_id is None and not os.path.exists(session.final_path):
            raise HTTPException(status_code=422, detail="Source file no longer exists on disk")
        source_ctx = (
            UploadArtifactClient().materialize(artifact_id, session.filename)
            if artifact_id
            else nullcontext(session.final_path)
        )
        try:
            with source_ctx as source_path:
                bbox = await asyncio.to_thread(extract_bbox_from_file, source_path)
                if bbox:
                    crs_str = await asyncio.to_thread(get_crs_from_file, source_path)
        except Exception as exc:
            # Lease artifact bisa sudah dilepas setelah tiling; beri pesan yang jujur, bukan 500.
            raise HTTPException(status_code=422, detail=f"Source file unavailable: {exc}")

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

    updated = await repo.update(
        layer_id=layer_id,
        bbox_west=west,
        bbox_south=south,
        bbox_east=east,
        bbox_north=north,
        file_metadata=new_metadata,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Layer not found")

    # Keep the CSW record spatial extent consistent with the layer row.
    await asyncio.to_thread(sync_layer, updated)

    return {
        "message": "BBox synced",
        "layer_id": layer_id,
        "bbox": [west, south, east, north],
        "crs": crs_str,
    }


@router.post("/{layer_id}/retile")
async def retile_layer(
    layer_id: str,
    max_zoom: int = Query(..., ge=0, le=22, description="Maximum zoom level for regenerated tiles"),
    authorization: Optional[str] = Header(default=None),
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
    # Artifact handoff: worker process_tiling_task sudah handle materialize "artifact://",
    # jadi jangan tolak di pre-check ini.
    is_artifact = upload_session.final_path.startswith("artifact://")
    if not is_artifact and not Path(upload_session.final_path).exists():
        raise HTTPException(status_code=404, detail="Source file missing from disk")

    if layer.file_type not in ("vector", "raster"):
        raise HTTPException(status_code=422, detail="Only SHP/vector and raster layers can be retiled")

    temporary_lease_id = None
    if is_artifact:
        if not authorization:
            raise HTTPException(status_code=401, detail="Authorization is required to retile an artifact source")
        artifact_id = upload_session.final_path.removeprefix("artifact://")
        client = None
        try:
            client = UploadArtifactClient()
            grant_id = await asyncio.to_thread(client.create_user_grant, artifact_id, authorization)
            lease = await asyncio.to_thread(
                client.acquire_lease, artifact_id, grant_id, f"retile:{layer.id}:{uuid.uuid4()}",
            )
            temporary_lease_id = str(lease["lease_id"])
            await session_repo.set_artifact_lease(upload_session.id, temporary_lease_id)
        except Exception as exc:
            if temporary_lease_id and client:
                try:
                    await asyncio.to_thread(client.release_lease, artifact_id, temporary_lease_id)
                except Exception:
                    pass
            raise HTTPException(status_code=424, detail="Source artifact is unavailable for retile") from exc

    output_format = upload_session.output_format or ("mvt" if layer.layer_type == "mvt" else "raster")
    try:
        task = process_tiling_task.delay(
            upload_session.id, layer.id,
            layer.file_type, upload_session.final_path, output_format, max_zoom
        )
    except Exception:
        if temporary_lease_id:
            await asyncio.to_thread(client.release_lease, artifact_id, temporary_lease_id)
            await session_repo.set_artifact_lease(upload_session.id, None)
        raise
    await session_repo.start_tiling(upload_session.id, task.id, output_format, max_zoom)
    return {"message": "Retiling queued", "upload_id": upload_session.id, "max_zoom": max_zoom}


_DOWNLOADABLE_ESRI_TYPES = ("esri_mapserver", "esri_featureserver")


@router.post("/{layer_id}/download")
async def trigger_layer_download(
    layer_id: str,
    req: Optional[EsriDownloadRequest] = None,
    repo: LayerRepository = Depends(_get_layer_repo),
):
    from app.infrastructure.services.esri_downloader import esri_service_base

    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")
    if layer.layer_type not in _DOWNLOADABLE_ESRI_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Layer type '{layer.layer_type}' is not downloadable; only Esri MapServer/FeatureServer layers are supported.",
        )
    if not esri_service_base(layer.tile_url_template or ""):
        raise HTTPException(status_code=422, detail="Layer URL is not a valid Esri MapServer/FeatureServer URL")

    current = (layer.file_metadata or {}).get("download_process") or {}
    if current.get("status") in ("pending", "processing"):
        raise HTTPException(status_code=409, detail="Download already in progress for this layer")

    output_formats = req.output_formats if req and req.output_formats else None

    # Baca proxy_url dan token dari file_metadata (per-layer config)
    meta = layer.file_metadata or {}
    proxy_url = meta.get("proxy_url", "")
    token = meta.get("token", "")

    # Preserve existing file_metadata — jangan timpa proxy_url/token
    await repo.update(layer_id, file_metadata={
        **meta,
        "download_process": {"status": "pending", "percent": 0},
    })
    task = download_esri_layer_task.delay(
        layer_id, output_formats=output_formats, proxy_url=proxy_url, token=token,
    )
    await repo.update(layer_id, file_metadata={
        **meta,
        "download_process": {"status": "pending", "percent": 0, "task_id": task.id, "output_formats": output_formats},
    })

    return APIResponse.success(
        message="Download queued",
        data={"layer_id": layer_id, "task_id": task.id, "output_formats": output_formats},
    )


@router.get("/{layer_id}/download/status")
async def get_layer_download_status(
    layer_id: str,
    repo: LayerRepository = Depends(_get_layer_repo),
):
    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")
    progress = (layer.file_metadata or {}).get("download_process")
    if not progress:
        raise HTTPException(status_code=404, detail="No download has been started for this layer")
    return APIResponse.success(message="Download status", data=progress)


@router.get("/{layer_id}/download/files")
async def list_layer_download_files(
    layer_id: str,
    repo: LayerRepository = Depends(_get_layer_repo),
):
    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")

    download_dir = Path(settings.DOWNLOAD_DIR) / layer_id
    if not download_dir.exists():
        raise HTTPException(status_code=404, detail="No downloaded files for this layer")

    files = []
    for f in sorted(download_dir.rglob("*")):
        if f.is_file():
            rel = f.relative_to(settings.DOWNLOAD_DIR)
            files.append({
                "path": str(rel),
                "size": _fmt_size(f.stat().st_size),
                "url": f"/downloads/{rel}",
            })
    return APIResponse.success(message="Downloaded files", data=files)


@router.delete("/{layer_id}/download")
async def cancel_layer_download(
    layer_id: str,
    repo: LayerRepository = Depends(_get_layer_repo),
):
    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")
    current = (layer.file_metadata or {}).get("download_process") or {}
    if current.get("status") not in ("pending", "processing"):
        raise HTTPException(status_code=422, detail="No active download to cancel")

    await repo.update(layer_id, file_metadata={
        "download_process": {**current, "status": "cancelled"}
    })
    return APIResponse.success(message="Download cancelled", data={"layer_id": layer_id})


@router.post("/external", response_model=LayerResponse)
async def add_external_layer(
    req: ExternalLayerRequest,
    repo: LayerRepository = Depends(_get_layer_repo),
):
    from app.infrastructure.services.bbox_extractor import extract_bbox

    # The UI uses `params`; manual API clients commonly send `file_metadata`.
    # Normalize both shapes before bbox extraction and persistence.
    file_metadata = dict(req.file_metadata or {})
    file_metadata.update(req.params or {})

    # Fetch bbox dari remote service (jika tidak override di request)
    bbox_result = None
    if req.bbox and len(req.bbox) == 4:
        bbox_result = tuple(req.bbox)
    else:
        bbox_result = await asyncio.to_thread(
            extract_bbox,
            req.layer_type,
            req.source_url,
            file_metadata,
        )

    filename_without_ext = Path(req.filename).stem
    base_code = slugify(filename_without_ext)
    unique_code = await generate_unique_code(base_code, repo.code_exists)

    # Fetch available sublayers for the selected external service.
    if req.layer_type == 'esri_mapserver':
        layers_list = await asyncio.to_thread(_fetch_esri_mapserver_layers, req.source_url)
        if layers_list:
            file_metadata['availableLayers'] = layers_list
    elif req.layer_type == 'wms':
        layers_list = await asyncio.to_thread(_fetch_wms_layers, req.source_url)
        if layers_list:
            file_metadata['availableLayers'] = layers_list

    layer = Layer(
        id=str(uuid.uuid4()),
        code=unique_code,
        filename=req.filename,
        file_type="external",
        layer_type=req.layer_type,
        tile_url_template=req.source_url,
        file_metadata=file_metadata,
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
            if all(v is not None for v in [created.bbox_west, created.bbox_south, created.bbox_east, created.bbox_north])
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


def _postgis_table_names(postgis: dict) -> list[str]:
    datasets = postgis.get("datasets") or []
    tables = [
        dataset["table"]
        for dataset in datasets
        if isinstance(dataset, dict)
        and dataset.get("schema", "geodata") == "geodata"
        and dataset.get("table")
    ]
    if not tables and postgis.get("schema") == "geodata" and postgis.get("table"):
        tables.append(postgis["table"])
    return list(dict.fromkeys(tables))


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

    postgis = (layer.file_metadata or {}).get("postgis") or {}
    for table_name in _postgis_table_names(postgis):
        items.append({
            "type": "postgis_table",
            "label": "PostGIS table",
            "detail": f"geodata.{table_name}",
        })

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

    # Downloaded Esri data on disk
    download_dir = Path(settings.DOWNLOAD_DIR) / layer_id
    if download_dir.exists():
        try:
            size = sum(f.stat().st_size for f in download_dir.rglob('*') if f.is_file())
            items.append({"type": "download_files", "label": "Downloaded data files", "detail": _fmt_size(size)})
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

    # Drop the owned dynamic table before any other destructive work. If this
    # fails, retain the Layer and its other files so deletion can be retried.
    postgis = (layer.file_metadata or {}).get("postgis") or {}
    postgis_tables = _postgis_table_names(postgis)
    if postgis_tables:
        from app.infrastructure.services.shapefile_import_service import drop_geodata_tables

        try:
            await asyncio.to_thread(
                drop_geodata_tables,
                db.get_engine(),
                postgis_tables,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to drop PostGIS tables {', '.join(postgis_tables)}: {exc}",
            ) from exc

    # 1. Delete tile files from disk
    tile_dir = Path(settings.TILES_DIR) / layer_id
    if tile_dir.exists():
        try:
            shutil.rmtree(tile_dir, ignore_errors=True)
        except OSError:
            pass

    # 1b. Delete downloaded Esri data from disk
    download_dir = Path(settings.DOWNLOAD_DIR) / layer_id
    if download_dir.exists():
        shutil.rmtree(download_dir, ignore_errors=True)

    # 2. Delete DB row first (removes FK constraint to UploadSession).
    # A published survey project references the layer via projects.layer_id —
    # clear that FK first or the delete violates projects_layer_id_fkey.
    await ProjectRepository(layer_repo.session).unlink_layer(layer_id)
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
    layerIndex: int = Query(None),
    layerName: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
    layer_repo: LayerRepository = Depends(_get_layer_repo),
    session_repo: UploadSessionRepository = Depends(_get_session_repo),
):
    usecase = GetLayerFieldsUseCase(layer_repo, session_repo)
    try:
        return await usecase.execute(
            layer_id,
            layer_index=layerIndex,
            layer_name=layerName,
            authorization=authorization,
        )
    except (LayerNotFoundError, LayerFieldsUnavailableError) as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    except LayerSourceUnavailableError as exc:
        raise HTTPException(status_code=424, detail=exc.message)


@router.get("/{layer_id}/fields/{field_name}/values", response_model=FieldUniqueValuesResponse)
async def get_field_unique_values(
    layer_id: str,
    field_name: str,
    layer_repo: LayerRepository = Depends(_get_layer_repo),
    session_repo: UploadSessionRepository = Depends(_get_session_repo),
):
    usecase = GetFieldUniqueValuesUseCase(layer_repo, session_repo)
    try:
        return await usecase.execute(layer_id, field_name)
    except (LayerNotFoundError, LayerFieldsUnavailableError) as exc:
        raise HTTPException(status_code=404, detail=exc.message)


@router.get("/{layer_id}/features/bbox", response_model=BboxFeaturesResponse)
async def get_features_in_bbox(
    layer_id: str,
    west: float = Query(...),
    south: float = Query(...),
    east: float = Query(...),
    north: float = Query(...),
    limit: int = Query(default=200, le=500),
    layer_repo: LayerRepository = Depends(_get_layer_repo),
    session_repo: UploadSessionRepository = Depends(_get_session_repo),
):
    usecase = GetFeaturesInBboxUseCase(layer_repo, session_repo)
    try:
        return await usecase.execute(layer_id, west, south, east, north, limit)
    except (LayerNotFoundError, LayerFieldsUnavailableError) as exc:
        raise HTTPException(status_code=404, detail=exc.message)


@router.get("/{layer_id}/features", response_model=FeatureQueryResponse)
async def query_features(
    layer_id: str,
    lon: float,
    lat: float,
    authorization: Optional[str] = Header(default=None),
    layer_repo: LayerRepository = Depends(_get_layer_repo),
    session_repo: UploadSessionRepository = Depends(_get_session_repo),
):
    usecase = QueryLayerFeaturesUseCase(layer_repo, session_repo)
    try:
        return await usecase.execute(layer_id, lon, lat, authorization=authorization)
    except LayerSourceUnavailableError as exc:
        raise HTTPException(status_code=424, detail=exc.message)


@router.post("/{layer_id}/mbtiles")
async def trigger_mbtiles(layer_id: str, repo: LayerRepository = Depends(_get_layer_repo)):
    from app.workers.tasks import generate_mbtiles_task

    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(404, "Layer not found")
    if layer.layer_type not in ("tile", "mvt"):
        raise HTTPException(400,
            f"MBTiles export only supports tiled layers (tile/mvt), got '{layer.layer_type}'")
    tiles_dir = Path(settings.TILES_DIR) / layer_id
    if not tiles_dir.exists():
        raise HTTPException(400, "No tiles on disk for this layer; run tiling first")
    task = generate_mbtiles_task.delay(layer_id=layer_id)
    return APIResponse.success(message="MBTiles generation started",
        data={"layer_id": layer_id, "task_id": task.id, "status": "processing"})


@router.get("/{layer_id}/mbtiles/status")
async def mbtiles_status(layer_id: str, repo: LayerRepository = Depends(_get_layer_repo)):
    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(404, "Layer not found")
    meta = (layer.file_metadata or {}).get("mbtiles", {})
    return APIResponse.success(data={
        "layer_id": layer_id,
        "status": layer.mbtiles_status,
        "size_bytes": layer.mbtiles_size_bytes,
        "progress": meta,
        "download_url": f"/api/v1/layers/{layer_id}/mbtiles/download"
                        if layer.mbtiles_status == "done" else None,
    })


@router.get("/{layer_id}/mbtiles/download")
async def download_mbtiles(layer_id: str, repo: LayerRepository = Depends(_get_layer_repo)):
    from fastapi.responses import FileResponse

    layer = await repo.get_by_id(layer_id)
    if not layer or layer.mbtiles_status != "done" or not layer.mbtiles_path:
        raise HTTPException(404, "MBTiles not available for this layer")
    file_path = Path(settings.MBTILES_DIR) / layer.mbtiles_path
    if not file_path.exists():
        raise HTTPException(404, "MBTiles file missing from disk")
    return FileResponse(path=str(file_path),
        media_type="application/vnd.mapbox-vector-tile" if layer.layer_type == "mvt"
                   else "application/x-sqlite3",
        filename=f"{layer.code or layer_id}.mbtiles")
