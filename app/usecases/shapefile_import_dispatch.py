"""Centralized enqueueing for explicitly requested shapefile imports."""

from __future__ import annotations

import uuid

from app.domain.models import ImportStatus, UploadSession
from app.infrastructure.db.repository import UploadSessionRepository
from app.infrastructure.services.shapefile_import_service import build_import_table_name


def is_shapefile_zip(filename: str) -> bool:
    return filename.lower().endswith(".zip")


async def dispatch_shapefile_import(
    upload: UploadSession,
    repo: UploadSessionRepository,
) -> str | None:
    if not is_shapefile_zip(upload.filename):
        return None
    if upload.import_status in {
        ImportStatus.pending,
        ImportStatus.processing,
        ImportStatus.completed,
        ImportStatus.cancelled,
    }:
        return upload.import_task_id

    from app.workers.tasks import import_shapefile_task

    task_id = str(uuid.uuid4())
    table_name = build_import_table_name(upload.filename, upload.layer_id)
    await repo.queue_import(upload.id, task_id, table_name)
    try:
        import_shapefile_task.apply_async(
            kwargs={"upload_id": upload.id},
            task_id=task_id,
        )
    except Exception as exc:
        await repo.set_import_status(upload.id, ImportStatus.failed, str(exc))
        return None
    return task_id
