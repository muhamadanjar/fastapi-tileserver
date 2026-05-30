from fastapi import APIRouter

from app.api.v1.endpoints import tiles, upload, layers, csw

api_router = APIRouter()
api_router.include_router(tiles.router, tags=["tiles"])
api_router.include_router(upload.router)
api_router.include_router(layers.router)
api_router.include_router(csw.router)
