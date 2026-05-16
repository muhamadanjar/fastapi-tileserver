from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import settings


# Connect args differ for SQLite vs PostgreSQL
_sync_connect_args = {} if settings.SESSIONS_USE_POSTGRESQL else {"check_same_thread": False}
_async_connect_args = {} if settings.SESSIONS_USE_POSTGRESQL else {"check_same_thread": False}

sync_engine = create_engine(
    settings.SESSIONS_DB_URL,
    connect_args=_sync_connect_args,
)

async_engine = create_async_engine(
    settings.SESSIONS_DB_URL_ASYNC,
    connect_args=_async_connect_args,
)

AsyncSessionLocal = sessionmaker(
    async_engine, class_=AsyncSession, expire_on_commit=False
)


async def create_db_and_tables() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_async_session():
    async with AsyncSessionLocal() as session:
        yield session


def get_sync_session():
    with Session(sync_engine) as session:
        yield session
