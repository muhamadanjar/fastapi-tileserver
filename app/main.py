import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.api.v1.api import api_router
from app.api.v1.endpoints.mvt import router as mvt_router


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)


@app.on_event("startup")
async def _init_csw():
    from sqlmodel import select
    from app.domain.models import Layer
    from app.infrastructure.db.connection import db
    from app.infrastructure.services.csw_sync import init_csw_db, sync_layer

    await asyncio.to_thread(init_csw_db)

    def _sync_existing():
        with db.get_session() as session:
            layers = session.exec(select(Layer)).all()
            for layer in layers:
                try:
                    sync_layer(layer)
                except Exception:
                    pass

    await asyncio.to_thread(_sync_existing)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.get_cors_methods(),
    allow_headers=settings.get_cors_headers(),
)

app.include_router(mvt_router)
app.mount("/tiles", StaticFiles(directory=settings.TILES_DIR), name="tiles")
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    return {"message": "FastAPI TileServer is running."}
