from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import settings


sync_engine = create_engine(
    settings.SESSIONS_DB_URL,
    connect_args={"check_same_thread": False},
)

async_engine = create_async_engine(
    settings.SESSIONS_DB_URL_ASYNC,
    connect_args={"check_same_thread": False},
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
