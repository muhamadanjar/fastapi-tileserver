"""Esri service discovery and download estimate endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from app.core.response import APIResponse
from app.core.config import settings
from app.core.utils import slugify
from app.domain.schemas import (
    EsriDiscoverRequest, EsriDiscoverResponse, EsriDiscoverLayerInfo,
    EsriEstimateRequest, EsriEstimateResponse, EsriLayerEstimate,
)
from app.domain.models import Layer, LayerType
from app.infrastructure.db.connection import get_async_session
from app.infrastructure.db.repository import LayerRepository
from app.infrastructure.services.esri_estimator import EsriEstimator
from app.infrastructure.services.esri_client import EsriClient
from app.infrastructure.services.esri_downloader import esri_service_base

router = APIRouter(prefix="/esri", tags=["esri"])


def _get_layer_repo(session=Depends(get_async_session)) -> LayerRepository:
    return LayerRepository(session)


@router.post("/discover", response_model=EsriDiscoverResponse)
async def discover_esri_service(req: EsriDiscoverRequest):
    """Scan an Esri service URL and return detected layers + metadata."""
    base_url = esri_service_base(req.url)
    if not base_url:
        raise HTTPException(
            status_code=422,
            detail=f"Not a MapServer/FeatureServer URL: {req.url}",
        )

    def _discover():
        client = EsriClient(base_url, proxy_url=req.proxy_url, token=req.token)
        service_info = client.get_service_info()
        render_only = client.is_render_only_service(service_info)

        # Detect service type
        service_type = "Unknown"
        for part in reversed(base_url.split("/")):
            if part.lower() in ("mapserver", "featureserver", "imageserver", "vectortileserver"):
                service_type = part
                break

        layers = []
        skipped = []

        if render_only:
            rl = client.build_render_only_layer(service_info)
            layers.append(EsriDiscoverLayerInfo(
                id=-1,
                name=rl["name"],
                geometry_type="Image Export",
                query_supported=False,
            ))
        else:
            layer_entries = client.get_layers_from_service()
            for entry in layer_entries:
                layer_id = entry.get("id")
                name = entry.get("name") or f"Layer {layer_id}"
                if entry.get("subLayerIds"):
                    skipped.append({"id": layer_id, "name": name, "reason": "group layer"})
                    continue

                try:
                    detail = client.get_layer_info(layer_id)
                except Exception:
                    skipped.append({"id": layer_id, "name": name, "reason": "metadata fetch failed"})
                    continue

                geom = client.normalize_geometry_type(detail.get("geometryType"))
                if geom == "Unknown":
                    geom = client.infer_geometry_type(layer_id, detail)

                query_ok = client.is_query_supported(detail) or client.can_query_layer(layer_id)
                if geom == "Unknown" and not query_ok:
                    skipped.append({"id": layer_id, "name": name, "reason": "no geometry or query unsupported"})
                    continue

                layers.append(EsriDiscoverLayerInfo(
                    id=layer_id,
                    name=name,
                    geometry_type=geom,
                    query_supported=query_ok,
                ))

        return service_type, layers, skipped, render_only

    service_type, layers, skipped, render_only = await asyncio.to_thread(_discover)

    return EsriDiscoverResponse(
        service_type=service_type,
        service_url=base_url,
        layers=layers,
        render_only=render_only,
        skipped=skipped,
    )


@router.post("/layers/{layer_id}/estimate", response_model=EsriEstimateResponse)
async def estimate_layer_download(
    layer_id: str,
    req: EsriEstimateRequest,
    repo: LayerRepository = Depends(_get_layer_repo),
):
    """Estimate download size/complexity for a saved Esri layer."""
    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")
    if layer.layer_type not in ("esri_mapserver", "esri_featureserver"):
        raise HTTPException(
            status_code=422,
            detail=f"Estimate only available for Esri MapServer/FeatureServer layers, got '{layer.layer_type}'.",
        )

    service_url = layer.tile_url_template
    if not esri_service_base(service_url):
        raise HTTPException(status_code=422, detail="Invalid Esri service URL")

    # Baca proxy_url dan token dari file_metadata (per-layer config)
    meta = layer.file_metadata or {}
    proxy_url = meta.get("proxy_url", "")
    token = meta.get("token", "")

    def _estimate():
        estimator = EsriEstimator(
            service_url, proxy_url=proxy_url, token=token,
        )
        return estimator.estimate_service(
            output_formats=req.output_formats,
            chunk_size=req.chunk_size,
        )

    result = await asyncio.to_thread(_estimate)

    layer_estimates = [
        EsriLayerEstimate(**est) for est in result["layers"]
    ]

    return EsriEstimateResponse(
        service_url=result["service_url"],
        total_layers=result["total_layers"],
        total_features=result["total_features"],
        total_chunks=result["total_chunks"],
        low_confidence_count=result["low_confidence_count"],
        layers=layer_estimates,
    )


@router.get("/downloads/{layer_id:path}")
async def get_esri_download_file(layer_id: str):
    """Serve downloaded Esri files from the download directory.

    URL pattern: /api/v1/esri/downloads/{layer_id}/0_jalan/shp/jalan.zip
    """
    from fastapi.responses import FileResponse

    # layer_id here is actually a relative path like "abc123/0_jalan/shp/file.zip"
    parts = layer_id.split("/", 1)
    if len(parts) < 2:
        raise HTTPException(status_code=404, detail="Invalid download path")

    layer_uuid = parts[0]
    rel_path = parts[1]

    download_dir = Path(settings.DOWNLOAD_DIR) / layer_uuid
    file_path = download_dir / rel_path

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Download file not found")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Path is a directory, not a file")

    # Security: ensure path doesn't escape download_dir
    try:
        file_path.resolve().relative_to(download_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    media_type = {
        ".geojson": "application/geo+json",
        ".json": "application/json",
        ".zip": "application/zip",
        ".gpkg": "application/geopackage+sqlite3",
        ".kmz": "application/vnd.google-earth.kmz",
        ".kml": "application/vnd.google-earth.kml+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".tif": "image/tiff",
    }.get(file_path.suffix.lower(), "application/octet-stream")

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=file_path.name,
    )
