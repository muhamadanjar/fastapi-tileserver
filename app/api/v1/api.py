from fastapi import APIRouter

from app.api.v1.endpoints import tiles, upload

api_router = APIRouter()
api_router.include_router(tiles.router, tags=["tiles"])
api_router.include_router(upload.router)
