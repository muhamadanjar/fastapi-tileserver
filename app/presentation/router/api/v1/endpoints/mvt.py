import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.core.config import settings

router = APIRouter(tags=["mvt"])

UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)


@router.get("/tiles/{layer_id}/{z}/{x}/{y}.pbf")
async def get_mvt_tile(layer_id: str, z: int, x: int, y: int) -> Response:
    if not UUID_PATTERN.match(layer_id):
        raise HTTPException(status_code=400, detail="Invalid layer_id")

    base = Path(settings.TILES_DIR).resolve()
    tile_path = (base / layer_id / str(z) / str(x) / f"{y}.pbf").resolve()

    try:
        tile_path.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not tile_path.exists():
        raise HTTPException(status_code=404, detail="Tile not found")

    return Response(
        content=tile_path.read_bytes(),
        media_type="application/x-protobuf",
        headers={
            "Access-Control-Allow-Origin": "*",
        },
    )


def _group_layers(group_code: str):
    from app.domain.map_batches import MapError
    from app.infrastructure.db.catalog import SyncStore
    from app.infrastructure.db.connection import db

    with SyncStore(db.get_session).transaction() as records:
        group = next((candidate for candidate in records.groups() if candidate.code == group_code), None)
        if group is None or group.status != "published":
            raise MapError("Published group not found", 404)
        return group, [records.layer(member.layer_id) for member in group.members]


@router.get("/tiles/_group/{group_code}/{z}/{x}/{y}.png")
async def get_group_raster_tile(group_code: str, z: int, x: int, y: int) -> Response:
    from app.infrastructure.services.map_renderer import FileBackedMapRenderer
    from starlette.concurrency import run_in_threadpool

    try:
        group, layers = await run_in_threadpool(_group_layers, group_code)
        if group.output_format != "raster":
            raise HTTPException(status_code=404, detail="Raster group not found")
        tile = await run_in_threadpool(FileBackedMapRenderer().compose_raster_tile, group, layers, z, x, y)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=getattr(exc, "status", 404), detail=str(exc))
    if tile is None:
        raise HTTPException(status_code=404, detail="Tile not found")
    return Response(content=tile, media_type="image/png")


@router.get("/tiles/_group/{group_code}/{z}/{x}/{y}.pbf")
async def get_group_mvt_tile(group_code: str, z: int, x: int, y: int) -> Response:
    from app.infrastructure.services.map_renderer import FileBackedMapRenderer
    from starlette.concurrency import run_in_threadpool

    try:
        group, layers = await run_in_threadpool(_group_layers, group_code)
        if group.output_format != "mvt":
            raise HTTPException(status_code=404, detail="MVT group not found")
        tile = await run_in_threadpool(FileBackedMapRenderer().compose_mvt_tile, group, layers, z, x, y)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=getattr(exc, "status", 404), detail=str(exc))
    if tile is None:
        raise HTTPException(status_code=404, detail="Tile not found")
    return Response(content=tile, media_type="application/x-protobuf")
