import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.auth_middleware import JWTAuthenticationMiddleware
from app.api.v1.api import api_router
from app.api.v1.endpoints.mvt import router as mvt_router
from app.infrastructure.db.connection import db

_csw_logger = logging.getLogger("app.csw_init")

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

    try:
        await asyncio.to_thread(init_csw_db)
        _csw_logger.info("CSW records table initialized.")
    except Exception as exc:
        _csw_logger.error("CSW table init failed: %s", exc, exc_info=True)
        return

    def _sync_existing():
        failed = 0
        with db.get_session() as session:
            layers = session.exec(select(Layer)).all()
            for layer in layers:
                try:
                    sync_layer(layer)
                except Exception as e:
                    failed += 1
                    _csw_logger.warning(
                        "CSW sync failed for layer %s: %s", layer.id, e
                    )
        if failed:
            _csw_logger.warning("CSW startup sync: %d layers failed.", failed)

    await asyncio.to_thread(_sync_existing)

app.add_middleware(JWTAuthenticationMiddleware, settings=settings)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.get_cors_methods(),
    allow_headers=settings.get_cors_headers(),
)

app.include_router(mvt_router)
app.mount("/tiles", StaticFiles(directory=settings.TILES_DIR), name="tiles")
app.mount("/downloads", StaticFiles(directory=settings.DOWNLOAD_DIR), name="downloads")
app.mount("/attachments", StaticFiles(directory=settings.ATTACHMENTS_DIR), name="attachments")
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    return {"message": "FastAPI TileServer is running."}


@app.get("/health")
async def health_check() -> dict:
    db_ok = await db.health_check()
    return {
        "status": "healthy" if db_ok else "unhealthy",
        "database": "connected" if db_ok else "disconnected",
        "service": "tileserver_api",
    }
