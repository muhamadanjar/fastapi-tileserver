from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.api.v1.api import api_router
from app.infrastructure.db.connection import create_db_and_tables
from app.infrastructure.broker.publisher import RabbitMQPublisher


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    publisher = RabbitMQPublisher()
    await publisher.connect()
    app.state.publisher = publisher
    yield
    await publisher.close()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

app.mount("/tiles", StaticFiles(directory=settings.TILES_DIR), name="tiles")
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    return {"message": "FastAPI TileServer is running."}
