from fastapi import APIRouter

from app.api.v1.endpoints import tiles, upload, layers, csw, esri, projects, geocoding, analysis, batches

api_router = APIRouter()
api_router.include_router(batches.router, tags=["batches"])
api_router.include_router(batches.groups_router, tags=["groups"])
api_router.include_router(tiles.router, tags=["tiles"])
api_router.include_router(upload.router)
api_router.include_router(layers.router)
api_router.include_router(csw.router)
api_router.include_router(esri.router)
api_router.include_router(projects.router)
api_router.include_router(geocoding.router)
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])