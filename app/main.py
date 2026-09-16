import asyncio
import logging
import os
import subprocess

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.presentation.middleware.auth_middleware import JWTAuthenticationMiddleware
from app.presentation.middleware.analysis_upload_limit import AnalysisUploadLimitMiddleware
from app.presentation.router.api.v1.api import api_router
from app.presentation.router.api.v1.endpoints.mvt import router as mvt_router
from app.infrastructure.db.connection import db

from app.infrastructure.observability.otel_logging import configure_otel_logging

from app.infrastructure.health import check_all_infrastructure


_csw_logger = logging.getLogger("app.csw_init")


def _current_version() -> str:
    """Resolve tileserver version: env TILESERVER_VERSION > latest git tag > 0.0.0."""
    env_version = os.getenv("TILESERVER_VERSION")
    if env_version:
        return env_version
    try:
        tag = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return tag or "0.0.0"
    except Exception:
        return "0.0.0"


__version__ = _current_version()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=__version__,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)


@app.on_event("startup")
async def _init_otel_logging():
    app.state.otel_logging = configure_otel_logging(
        enabled=settings.OTEL_ENABLED,
        service_name=settings.OTEL_SERVICE_NAME,
        endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
    )


@app.on_event("shutdown")
async def _shutdown_otel_logging():
    otel_logging = getattr(app.state, "otel_logging", None)
    if otel_logging is not None:
        otel_logging.shutdown()


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

# app.add_middleware(JWTAuthenticationMiddleware, settings=settings)
app.add_middleware(AnalysisUploadLimitMiddleware, max_bytes=settings.ANALYSIS_MAX_UPLOAD_BYTES)
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
    return {"message": "FastAPI TileServer is running.", "version": __version__}


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint - verifies database, Redis, and RabbitMQ connectivity."""
    return await check_all_infrastructure()
