from pathlib import Path

from app.workers.celery_app import celery_app
from app.infrastructure.db.connection import db
from app.infrastructure.db.repository import SyncUploadSessionRepository, SyncLayerRepository
from app.infrastructure.services.tiling_service import TilingService
from app.infrastructure.services.csw_sync import sync_layer
from app.domain.models import JobStatus, Layer
from app.core.utils import slugify


@celery_app.task(bind=True, max_retries=3)
def process_tiling_task(self, upload_id: str, layer_id: str, file_type: str, source_path: str, output_format: str = "raster"):
    with db.get_session() as session:
        repo = SyncUploadSessionRepository(session)
        repo.set_status(upload_id, JobStatus.processing)

    try:
        style = None
        with db.get_session() as session:
            layer_repo = SyncLayerRepository(session)
            existing = layer_repo.get_by_id(layer_id)
            if existing and existing.file_metadata:
                style = existing.file_metadata.get("style")

        bounds = TilingService.process_tiling(file_type, Path(source_path), layer_id, output_format=output_format, style=style)
        with db.get_session() as session:
            upload_repo = SyncUploadSessionRepository(session)
            upload_repo.set_status(upload_id, JobStatus.done)

            upload_session = upload_repo.get_by_id(upload_id)
            if upload_session:
                if output_format == "mvt":
                    layer_type = "mvt"
                    tile_url = f"/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.pbf"
                else:
                    layer_type = "tile"
                    tile_url = f"/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.png"

                layer_repo = SyncLayerRepository(session)
                existing_layer = layer_repo.get_by_id(layer_id)
                if not existing_layer:
                    layer = Layer(
                        id=layer_id,
                        upload_session_id=upload_id,
                        code=slugify(upload_session.filename),
                        filename=upload_session.filename,
                        file_type=file_type,
                        layer_type=layer_type,
                        tile_url_template=tile_url,
                        bbox_west=bounds[0] if bounds else None,
                        bbox_south=bounds[1] if bounds else None,
                        bbox_east=bounds[2] if bounds else None,
                        bbox_north=bounds[3] if bounds else None,
                    )
                    layer_repo.create(layer)
                    try:
                        sync_layer(layer)
                    except Exception:
                        pass
    except Exception as exc:
        with db.get_session() as session:
            repo = SyncUploadSessionRepository(session)
            repo.set_status(upload_id, JobStatus.failed, error_message=str(exc))
        raise self.retry(exc=exc, countdown=5)
