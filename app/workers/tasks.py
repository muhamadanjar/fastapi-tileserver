from pathlib import Path
from sqlmodel import Session

from app.workers.celery_app import celery_app
from app.infrastructure.db.connection import sync_engine
from app.infrastructure.db.repository import SyncUploadSessionRepository, SyncLayerRepository
from app.infrastructure.services.tiling_service import TilingService
from app.domain.models import JobStatus, Layer
from app.core.utils import slugify


@celery_app.task(bind=True, max_retries=3)
def process_tiling_task(self, upload_id: str, layer_id: str, file_type: str, source_path: str):
    with Session(sync_engine) as session:
        repo = SyncUploadSessionRepository(session)
        repo.set_status(upload_id, JobStatus.processing)

    try:
        bounds = TilingService.process_tiling(file_type, Path(source_path), layer_id)
        with Session(sync_engine) as session:
            upload_repo = SyncUploadSessionRepository(session)
            upload_repo.set_status(upload_id, JobStatus.done)

            upload_session = upload_repo.get_by_id(upload_id)
            if upload_session:
                layer = Layer(
                    id=layer_id,
                    upload_session_id=upload_id,
                    code=slugify(upload_session.filename),
                    filename=upload_session.filename,
                    file_type=file_type,
                    layer_type='tile',
                    tile_url_template=f"/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png",
                    bbox_west=bounds[0] if bounds else None,
                    bbox_south=bounds[1] if bounds else None,
                    bbox_east=bounds[2] if bounds else None,
                    bbox_north=bounds[3] if bounds else None,
                )
                layer_repo = SyncLayerRepository(session)
                layer_repo.create(layer)
    except Exception as exc:
        with Session(sync_engine) as session:
            repo = SyncUploadSessionRepository(session)
            repo.set_status(upload_id, JobStatus.failed, error_message=str(exc))
        raise self.retry(exc=exc, countdown=5)
