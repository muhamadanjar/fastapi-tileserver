from pathlib import Path
from sqlmodel import Session

from app.workers.celery_app import celery_app
from app.infrastructure.db.connection import sync_engine
from app.infrastructure.db.repository import SyncUploadSessionRepository
from app.infrastructure.services.tiling_service import TilingService
from app.domain.models import JobStatus


@celery_app.task(bind=True, max_retries=3)
def process_tiling_task(self, upload_id: str, layer_id: str, file_type: str, source_path: str):
    with Session(sync_engine) as session:
        repo = SyncUploadSessionRepository(session)
        repo.set_status(upload_id, JobStatus.processing)

    try:
        TilingService.process_tiling(file_type, Path(source_path), layer_id)
        with Session(sync_engine) as session:
            repo = SyncUploadSessionRepository(session)
            repo.set_status(upload_id, JobStatus.done)
    except Exception as exc:
        with Session(sync_engine) as session:
            repo = SyncUploadSessionRepository(session)
            repo.set_status(upload_id, JobStatus.failed, error_message=str(exc))
        raise self.retry(exc=exc, countdown=5)
