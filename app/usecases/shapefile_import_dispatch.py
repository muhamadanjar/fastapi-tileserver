"""Centralized enqueueing for explicitly requested shapefile imports."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from app.domain.import_naming import build_import_table_name
from app.domain.models import ImportStatus, UploadSession
from app.domain.ports import UploadSessionRepositoryPort


def is_shapefile_zip(filename: str) -> bool:
    return filename.lower().endswith(".zip")


async def dispatch_shapefile_import(
    upload: UploadSession,
    repo: UploadSessionRepositoryPort,
    enqueue: Callable[[str, str], None],
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

    task_id = str(uuid.uuid4())
    table_name = build_import_table_name(upload.filename, upload.layer_id)
    await repo.queue_import(upload.id, task_id, table_name)
    try:
        enqueue(upload.id, task_id)
    except Exception as exc:
        await repo.set_import_status(upload.id, ImportStatus.failed, str(exc))
        return None
    return task_id
