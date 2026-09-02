from datetime import datetime, timezone
from typing import Optional

from sqlmodel import select
from sqlalchemy import func, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes as _sa_attrs
from sqlmodel import Session

from app.domain.models import UploadSession, Layer, JobStatus, ImportStatus, Project, Feature, Attachment
from sqlalchemy.orm import attributes
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

    async def get_by_artifact_handoff(self, handoff_id: str) -> Optional[UploadSession]:
        result = await self.session.execute(
            select(UploadSession).where(UploadSession.artifact_handoff_id == handoff_id)
        )
        return result.scalars().first()

    async def update_chunk_map(
        self,
        upload_id: str,
        chunk_index: int,
        chunk_bytes: int,
        uploaded_chunks: int,
        received_bytes: int,
    ) -> None:
        session_obj = await self.get_by_id(upload_id)
        if session_obj:
            cm = dict(session_obj.chunk_map or {})
            cm[str(chunk_index)] = chunk_bytes
            session_obj.chunk_map = cm
            attributes.flag_modified(session_obj, "chunk_map")
            session_obj.uploaded_chunks = uploaded_chunks
            session_obj.received_bytes = received_bytes
            session_obj.status = JobStatus.uploading
            session_obj.updated_at = datetime.now(timezone.utc)
            self.session.add(session_obj)
            await self.session.commit()

    async def mark_expired(self, upload_id: str) -> None:
        session_obj = await self.get_by_id(upload_id)
        if session_obj:
            session_obj.status = JobStatus.expired
            session_obj.updated_at = datetime.now(timezone.utc)
            self.session.add(session_obj)
            await self.session.commit()

    async def mark_complete(self, upload_id: str, final_path: str) -> None:
        session_obj = await self.get_by_id(upload_id)
        if session_obj:
            session_obj.final_path = final_path
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

    async def set_task_id(self, upload_id: str, task_id: str) -> None:
        session_obj = await self.get_by_id(upload_id)
        if session_obj:
            session_obj.celery_task_id = task_id
            self.session.add(session_obj)
            await self.session.commit()

    async def queue_import(self, upload_id: str, task_id: str, table_name: str) -> None:
        session_obj = await self.get_by_id(upload_id)
        if session_obj:
            session_obj.import_status = ImportStatus.pending
            session_obj.import_task_id = task_id
            session_obj.import_error = None
            session_obj.import_table_name = table_name
            session_obj.import_processed_rows = 0
            session_obj.import_total_rows = 0
            session_obj.imported_row_count = None
            session_obj.imported_at = None
            session_obj.updated_at = datetime.now(timezone.utc)
            self.session.add(session_obj)
            await self.session.commit()

    async def set_import_status(
        self,
        upload_id: str,
        status: ImportStatus,
        error: Optional[str] = None,
    ) -> None:
        session_obj = await self.get_by_id(upload_id)
        if session_obj:
            session_obj.import_status = status
            session_obj.import_error = error
            session_obj.updated_at = datetime.now(timezone.utc)
            self.session.add(session_obj)
            await self.session.commit()

    async def start_tiling(
        self,
        upload_id: str,
        task_id: str,
        output_format: str,
        max_zoom: Optional[int],
    ) -> None:
        session_obj = await self.get_by_id(upload_id)
        if session_obj:
            session_obj.celery_task_id = task_id
            session_obj.output_format = output_format
            session_obj.max_zoom = max_zoom
            session_obj.status = JobStatus.processing
            session_obj.updated_at = datetime.utcnow()
            self.session.add(session_obj)
            await self.session.commit()

    async def set_artifact_lease(self, upload_id: str, lease_id: Optional[str]) -> None:
        session_obj = await self.get_by_id(upload_id)
        if session_obj:
            session_obj.artifact_lease_id = lease_id
            session_obj.updated_at = datetime.utcnow()
            self.session.add(session_obj)
            await self.session.commit()

    async def delete(self, upload_id: str) -> bool:
        session_obj = await self.get_by_id(upload_id)
        if session_obj:
            await self.session.delete(session_obj)
            await self.session.commit()
            return True
        return False


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

    def set_task_id(self, upload_id: str, task_id: str) -> None:
        session_obj = self.get_by_id(upload_id)
        if session_obj:
            session_obj.celery_task_id = task_id
            self.session.add(session_obj)
            self.session.commit()

    def set_import_status(
        self,
        upload_id: str,
        status: ImportStatus,
        error: Optional[str] = None,
    ) -> None:
        session_obj = self.get_by_id(upload_id)
        if session_obj:
            session_obj.import_status = status
            session_obj.import_error = error
            session_obj.updated_at = datetime.now(timezone.utc)
            self.session.add(session_obj)
            self.session.commit()

    def update_import_progress(self, upload_id: str, processed: int, total: int) -> None:
        session_obj = self.get_by_id(upload_id)
        if session_obj:
            session_obj.import_processed_rows = processed
            session_obj.import_total_rows = total
            session_obj.updated_at = datetime.now(timezone.utc)
            self.session.add(session_obj)
            self.session.commit()

    def complete_import(
        self, upload_id: str, row_count: int, table_name: Optional[str] = None
    ) -> None:
        session_obj = self.get_by_id(upload_id)
        if session_obj:
            session_obj.import_status = ImportStatus.completed
            session_obj.import_error = None
            session_obj.import_processed_rows = row_count
            session_obj.import_total_rows = row_count
            session_obj.imported_row_count = row_count
            if table_name:
                session_obj.import_table_name = table_name
            session_obj.imported_at = datetime.now(timezone.utc)
            session_obj.updated_at = datetime.now(timezone.utc)
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

    def update_progress(self, layer_id: str, progress: dict) -> None:
        layer = self.get_by_id(layer_id)
        if layer:
            existing = dict(layer.file_metadata or {})
            existing["tile_process"] = progress
            layer.file_metadata = existing
            _sa_attrs.flag_modified(layer, "file_metadata")
            layer.updated_at = datetime.now(timezone.utc)
            self.session.add(layer)
            self.session.commit()

    def update_download_progress(self, layer_id: str, progress: dict) -> None:
        layer = self.get_by_id(layer_id)
        if layer:
            existing = dict(layer.file_metadata or {})
            existing["download_process"] = progress
            layer.file_metadata = existing
            _sa_attrs.flag_modified(layer, "file_metadata")
            layer.updated_at = datetime.now(timezone.utc)
            self.session.add(layer)
            self.session.commit()

    def get_download_progress(self, layer_id: str) -> Optional[dict]:
        layer = self.get_by_id(layer_id)
        if layer and layer.file_metadata:
            return layer.file_metadata.get("download_process")
        return None

    def code_exists(self, code: str) -> bool:
        result = self.session.exec(
            select(Layer).where(Layer.code == code)
        )
        return result.first() is not None

    def update_mbtiles(self, layer_id: str, *, status: str,
                       progress: Optional[dict] = None,
                       path: Optional[str] = None,
                       size_bytes: Optional[int] = None) -> None:
        layer = self.get_by_id(layer_id)
        if not layer:
            return
        meta = dict(layer.file_metadata or {})
        meta["mbtiles"] = {**(meta.get("mbtiles") or {}),
                           **(progress or {}), "status": status}
        layer.file_metadata = meta
        _sa_attrs.flag_modified(layer, "file_metadata")
        layer.mbtiles_status = status
        if path is not None:
            layer.mbtiles_path = path
        if size_bytes is not None:
            layer.mbtiles_size_bytes = size_bytes
        layer.updated_at = datetime.now(timezone.utc)
        self.session.add(layer)
        self.session.commit()


class LayerRepository:
    """Async variant for FastAPI endpoints."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_all(self) -> list[Layer]:
        result = await self.session.execute(select(Layer))
        return result.scalars().all()

    async def paginate(
        self,
        skip: int = 0,
        limit: int = 10,
        search: Optional[str] = None,
        sort_field: Optional[str] = None,
        sort_dir: str = "asc"
    ) -> dict:
        """Paginate layers with optional search and sorting. Returns dict with 'data' and 'metas'."""
        # Build base query
        query = select(Layer)

        # Apply search filter if provided
        if search:
            search_term = f"%{search}%"
            query = query.where(Layer.filename.ilike(search_term))

        # Apply sorting
        if sort_field:
            # Map frontend field names to database columns
            field_map = {
                "filename": Layer.filename,
                "layer_type": Layer.layer_type,
                "file_type": Layer.file_type,
                "created_at": Layer.created_at,
                "status": Layer.id,  # status is calculated, can't sort by it
            }
            sort_column = field_map.get(sort_field, Layer.created_at)
            sort_order = desc(sort_column) if sort_dir.lower() == "desc" else asc(sort_column)
            query = query.order_by(sort_order)
        else:
            # Default sort by created_at descending
            query = query.order_by(desc(Layer.created_at))

        # Get total count with filters applied
        count_query = select(func.count(Layer.id))
        if search:
            search_term = f"%{search}%"
            count_query = count_query.where(Layer.filename.ilike(search_term))

        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0

        # Get paginated data
        result = await self.session.execute(
            query.offset(skip).limit(limit)
        )
        data = result.scalars().all()

        # Calculate pagination metadata
        page_size = limit
        current_page = (skip // limit) + 1 if limit > 0 else 1
        total_pages = (total + limit - 1) // limit if limit > 0 else 1

        return {
            "data": data,
            "metas": {
                "total": total,
                "page": current_page,
                "page_size": page_size,
                "total_pages": total_pages,
                "has_next": current_page < total_pages,
                "has_prev": current_page > 1,
            }
        }

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
        bbox_west: Optional[float] = None,
        bbox_south: Optional[float] = None,
        bbox_east: Optional[float] = None,
        bbox_north: Optional[float] = None,
        abstract: Optional[str] = None,
        topic_category: Optional[str] = None,
        language: Optional[str] = None,
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
        # Hanya update bbox jika semua 4 values ada (atomic bbox, no partial data)
        if all(v is not None for v in [bbox_west, bbox_south, bbox_east, bbox_north]):
            layer.bbox_west = bbox_west
            layer.bbox_south = bbox_south
            layer.bbox_east = bbox_east
            layer.bbox_north = bbox_north
        if abstract is not None:
            layer.abstract = abstract
        if topic_category is not None:
            layer.topic_category = topic_category
        if language is not None:
            layer.language = language
        layer.updated_at = datetime.now(timezone.utc)
        self.session.add(layer)
        await self.session.commit()
        await self.session.refresh(layer)
        return layer

    async def code_exists(self, code: str) -> bool:
        result = await self.session.execute(
            select(Layer).where(Layer.code == code)
        )
        return result.scalars().first() is not None

    async def find_geoserver_layer_name(self, layer_name: str) -> Optional[Layer]:
        """Return the first layer whose geoserver.layer_name == given value.
        Used to reject duplicate WMS publishes of the same file/base."""
        result = await self.session.execute(
            select(Layer).where(
                Layer.file_metadata["geoserver"]["layer_name"].as_string() == layer_name
            )
        )
        return result.scalars().first()

    async def delete(self, layer_id: str) -> bool:
        layer = await self.get_by_id(layer_id)
        if layer:
            await self.session.delete(layer)
            await self.session.commit()
            return True
        return False

    async def update_mbtiles(self, layer_id: str, *, status: str,
                             progress: Optional[dict] = None,
                             path: Optional[str] = None,
                             size_bytes: Optional[int] = None) -> None:
        layer = await self.get_by_id(layer_id)
        if not layer:
            return
        meta = dict(layer.file_metadata or {})
        meta["mbtiles"] = {**(meta.get("mbtiles") or {}),
                           **(progress or {}), "status": status}
        layer.file_metadata = meta
        attributes.flag_modified(layer, "file_metadata")
        layer.mbtiles_status = status
        if path is not None:
            layer.mbtiles_path = path
        if size_bytes is not None:
            layer.mbtiles_size_bytes = size_bytes
        layer.updated_at = datetime.now(timezone.utc)
        self.session.add(layer)
        await self.session.commit()


class ProjectRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def unlink_layer(self, layer_id: str) -> None:
        """Clear layer_id on any project referencing the layer (before layer deletion)."""
        result = await self.session.execute(select(Project).where(Project.layer_id == layer_id))
        for project in result.scalars().all():
            project.layer_id = None
            project.updated_at = datetime.now(timezone.utc)
            self.session.add(project)
        await self.session.commit()

    async def create(self, project: Project) -> Project:
        self.session.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def get_by_id(self, project_id: str) -> Optional[Project]:
        result = await self.session.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Project]:
        result = await self.session.execute(select(Project).order_by(Project.created_at.desc()))
        return list(result.scalars().all())

    async def update(self, project: Project) -> Project:
        project.updated_at = datetime.now(timezone.utc)
        self.session.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def delete(self, project_id: str) -> bool:
        project = await self.get_by_id(project_id)
        if project is None:
            return False
        await self.session.delete(project)
        await self.session.commit()
        return True


class FeatureRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, feature: Feature) -> Feature:
        self.session.add(feature)
        await self.session.commit()
        await self.session.refresh(feature)
        return feature

    async def get_by_id(self, feature_id: str) -> Optional[Feature]:
        result = await self.session.execute(select(Feature).where(Feature.id == feature_id))
        return result.scalar_one_or_none()

    async def list_by_project(self, project_id: str) -> list[Feature]:
        result = await self.session.execute(
            select(Feature).where(Feature.project_id == project_id).order_by(Feature.created_at)
        )
        return list(result.scalars().all())

    async def update(self, feature: Feature) -> Feature:
        feature.updated_at = datetime.now(timezone.utc)
        self.session.add(feature)
        await self.session.commit()
        await self.session.refresh(feature)
        return feature

    async def delete(self, feature_id: str) -> bool:
        feature = await self.get_by_id(feature_id)
        if feature is None:
            return False
        await self.session.delete(feature)
        await self.session.commit()
        return True

    async def delete_by_project(self, project_id: str) -> int:
        features = await self.list_by_project(project_id)
        for f in features:
            await self.session.delete(f)
        await self.session.commit()
        return len(features)


class AttachmentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, attachment: Attachment) -> Attachment:
        self.session.add(attachment)
        await self.session.commit()
        await self.session.refresh(attachment)
        return attachment

    async def get_by_id(self, attachment_id: str) -> Optional[Attachment]:
        result = await self.session.execute(select(Attachment).where(Attachment.id == attachment_id))
        return result.scalar_one_or_none()

    async def list_by_project(self, project_id: str) -> list[Attachment]:
        result = await self.session.execute(
            select(Attachment).where(Attachment.project_id == project_id).order_by(Attachment.created_at)
        )
        return list(result.scalars().all())

    async def delete(self, attachment_id: str) -> bool:
        attachment = await self.get_by_id(attachment_id)
        if attachment is None:
            return False
        await self.session.delete(attachment)
        await self.session.commit()
        return True
