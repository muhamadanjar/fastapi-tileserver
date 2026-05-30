from datetime import datetime, timezone
from typing import Optional

from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes
from sqlmodel import Session

from app.domain.models import UploadSession, Layer, JobStatus
from app.core.exceptions import SessionNotFoundError


class UploadSessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, upload_session: UploadSession) -> UploadSession:
        self.session.add(upload_session)
        await self.session.commit()
        await self.session.refresh(upload_session)
        return upload_session

    async def get_by_id(self, upload_id: str) -> Optional[UploadSession]:
        result = await self.session.execute(
            select(UploadSession).where(UploadSession.id == upload_id)
        )
        return result.scalars().first()

    async def update_received_bytes(self, upload_id: str, received_bytes: int) -> None:
        session_obj = await self.get_by_id(upload_id)
        if session_obj:
            session_obj.received_bytes = received_bytes
            session_obj.updated_at = datetime.utcnow()
            self.session.add(session_obj)
            await self.session.commit()

    async def mark_complete(self, upload_id: str, final_path: str) -> None:
        session_obj = await self.get_by_id(upload_id)
        if session_obj:
            session_obj.final_path = final_path
            session_obj.status = JobStatus.pending
            session_obj.updated_at = datetime.utcnow()
            self.session.add(session_obj)
            await self.session.commit()

    async def set_status(
        self, upload_id: str, status: JobStatus, error_message: Optional[str] = None
    ) -> None:
        session_obj = await self.get_by_id(upload_id)
        if session_obj:
            session_obj.status = status
            session_obj.error_message = error_message
            session_obj.updated_at = datetime.utcnow()
            self.session.add(session_obj)
            await self.session.commit()


class SyncUploadSessionRepository:
    """Synchronous variant used by the worker process."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, upload_id: str) -> Optional[UploadSession]:
        result = self.session.exec(
            select(UploadSession).where(UploadSession.id == upload_id)
        )
        return result.first()

    def set_status(
        self, upload_id: str, status: JobStatus, error_message: Optional[str] = None
    ) -> None:
        session_obj = self.get_by_id(upload_id)
        if session_obj:
            session_obj.status = status
            session_obj.error_message = error_message
            session_obj.updated_at = datetime.utcnow()
            self.session.add(session_obj)
            self.session.commit()


class SyncLayerRepository:
    """Synchronous variant for the worker process."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, layer_id: str) -> Optional[Layer]:
        result = self.session.exec(
            select(Layer).where(Layer.id == layer_id)
        )
        return result.first()

    def create(self, layer: Layer) -> Layer:
        self.session.add(layer)
        self.session.commit()
        self.session.refresh(layer)
        return layer


class LayerRepository:
    """Async variant for FastAPI endpoints."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_all(self) -> list[Layer]:
        result = await self.session.execute(select(Layer))
        return result.scalars().all()

    async def get_by_id(self, layer_id: str) -> Optional[Layer]:
        result = await self.session.execute(
            select(Layer).where(Layer.id == layer_id)
        )
        return result.scalars().first()

    async def create(self, layer: Layer) -> Layer:
        self.session.add(layer)
        await self.session.commit()
        await self.session.refresh(layer)
        return layer

    async def update(
        self,
        layer_id: str,
        file_metadata: Optional[dict] = None,
        filename: Optional[str] = None,
        layer_type: Optional[str] = None,
        tile_url_template: Optional[str] = None,
    ) -> Optional[Layer]:
        layer = await self.get_by_id(layer_id)
        if not layer:
            return None
        if file_metadata is not None:
            existing = layer.file_metadata or {}
            merged = {**existing, **file_metadata}
            layer.file_metadata = merged
            attributes.flag_modified(layer, "file_metadata")
        if filename is not None:
            layer.filename = filename
        if layer_type is not None:
            layer.layer_type = layer_type
        if tile_url_template is not None:
            layer.tile_url_template = tile_url_template
        layer.updated_at = datetime.now(timezone.utc)
        self.session.add(layer)
        await self.session.commit()
        await self.session.refresh(layer)
        return layer

    async def delete(self, layer_id: str) -> bool:
        layer = await self.get_by_id(layer_id)
        if layer:
            await self.session.delete(layer)
            await self.session.commit()
            return True
        return False
