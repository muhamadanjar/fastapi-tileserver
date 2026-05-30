import asyncio
import logging
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncIterator, Iterator, Optional

from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import QueuePool
from sqlmodel import Session, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config.database import DatabaseSettings

logger = logging.getLogger(__name__)


class DatabaseConnection:
    def __init__(self, config: DatabaseSettings):
        self.config = config
        self._engine: Optional[Engine] = None
        self._async_engine: Optional[AsyncEngine] = None
        self._async_session_maker: Optional[async_sessionmaker[AsyncSession]] = None
        self._lock = asyncio.Lock()

    def get_engine(self) -> Engine:
        if self._engine is None:
            url = self.config.get_database_url(sync=True)
            kwargs = {**self.config.engine_kwargs, "poolclass": QueuePool}
            if "postgresql" in url:
                kwargs["connect_args"] = {"connect_timeout": self.config.connect_timeout}
            self._engine = create_engine(url, **kwargs)
            logger.info("Sync engine created.")
        return self._engine

    async def get_async_engine(self) -> AsyncEngine:
        if self._async_engine is None:
            async with self._lock:
                if self._async_engine is None:
                    url = self.config.get_database_url(sync=False)
                    kwargs = {**self.config.async_engine_kwargs}
                    if "postgresql" in url:
                        kwargs["connect_args"] = {"timeout": self.config.connect_timeout}
                    self._async_engine = create_async_engine(url, **kwargs)
                    self._async_session_maker = async_sessionmaker(
                        self._async_engine,
                        class_=AsyncSession,
                        expire_on_commit=False,
                    )
                    logger.info("Async engine created.")
        return self._async_engine

    @contextmanager
    def get_session(self) -> Iterator[Session]:
        session = Session(self.get_engine())
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @asynccontextmanager
    async def get_async_session(self) -> AsyncIterator[AsyncSession]:
        if self._async_session_maker is None:
            await self.get_async_engine()
        async with self._async_session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def connect(self) -> None:
        self.get_engine()
        await self.get_async_engine()

    async def disconnect(self) -> None:
        if self._async_engine:
            await self._async_engine.dispose()
        if self._engine:
            self._engine.dispose()
        self._engine = None
        self._async_engine = None
        self._async_session_maker = None

    async def health_check(self) -> bool:
        try:
            async with self.get_async_session() as session:
                from sqlalchemy import select
                result = await session.execute(select(1))
                return result.scalar() == 1
        except Exception:
            return False


db = DatabaseConnection(config=DatabaseSettings())


async def get_async_session() -> AsyncIterator[AsyncSession]:
    async with db.get_async_session() as session:
        yield session


def get_sync_session() -> Iterator[Session]:
    with db.get_session() as session:
        yield session
