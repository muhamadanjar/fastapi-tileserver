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
