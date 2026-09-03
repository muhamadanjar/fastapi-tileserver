from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.upload import start_shapefile_import
from app.domain.models import ImportStatus, JobStatus, UploadSession
from app.domain.schemas import JobStatusResponse, ShapefileImportedTable, ShapefileImportStatus
from app.usecases.shapefile_import_dispatch import dispatch_shapefile_import


class FakeUploadRepository:
    def __init__(self, upload: UploadSession | None = None):
        self.upload = upload
        self.queued = None
        self.failed = None

    async def get_by_id(self, upload_id: str):
        if self.upload and self.upload.id == upload_id:
            return self.upload
        return None

    async def queue_import(self, upload_id: str, task_id: str, table_name: str):
        self.queued = (upload_id, task_id, table_name)

    async def set_import_status(self, upload_id: str, status: ImportStatus, error: str):
        self.failed = (upload_id, status, error)


def _upload(filename: str) -> UploadSession:
    return UploadSession(
        id="upload-1",
        filename=filename,
        file_type="vector",
        layer_id="a1b2c3d4-1111-2222-3333-444455556666",
        total_size=10,
    )


@pytest.mark.asyncio
async def test_zip_dispatch_persists_task_identity_before_enqueue(monkeypatch):
    from app.workers import tasks

    apply_async = Mock()
    monkeypatch.setattr(tasks.import_shapefile_task, "apply_async", apply_async)
    repo = FakeUploadRepository()

    task_id = await dispatch_shapefile_import(_upload("Batas Desa.zip"), repo)

    assert task_id
    assert repo.queued == ("upload-1", task_id, "batas_desa_a1b2c3d4")
    apply_async.assert_called_once_with(kwargs={"upload_id": "upload-1"}, task_id=task_id)


@pytest.mark.asyncio
async def test_non_zip_does_not_enqueue(monkeypatch):
    from app.workers import tasks

    apply_async = Mock()
    monkeypatch.setattr(tasks.import_shapefile_task, "apply_async", apply_async)
    repo = FakeUploadRepository()

    task_id = await dispatch_shapefile_import(_upload("dataset.geojson"), repo)

    assert task_id is None
    assert repo.queued is None
    apply_async.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_is_idempotent_for_an_already_queued_upload(monkeypatch):
    from app.workers import tasks

    apply_async = Mock()
    monkeypatch.setattr(tasks.import_shapefile_task, "apply_async", apply_async)
    repo = FakeUploadRepository()
    upload = _upload("dataset.zip")
    upload.import_status = ImportStatus.pending
    upload.import_task_id = "existing-task"

    task_id = await dispatch_shapefile_import(upload, repo)

    assert task_id == "existing-task"
    assert repo.queued is None
    apply_async.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_start_queues_a_ready_zip(monkeypatch, tmp_path):
    from app.workers import tasks

    source = tmp_path / "dataset.zip"
    source.write_bytes(b"zip")
    upload = _upload(source.name)
    upload.status = JobStatus.uploaded
    upload.final_path = str(source)
    repo = FakeUploadRepository(upload)
    apply_async = Mock()
    monkeypatch.setattr(tasks.import_shapefile_task, "apply_async", apply_async)

    response = await start_shapefile_import(upload.id, repo)

    assert response["status"] == ImportStatus.pending
    assert response["task_id"]
    assert repo.queued == (upload.id, response["task_id"], "dataset_a1b2c3d4")
    apply_async.assert_called_once()


@pytest.mark.asyncio
async def test_explicit_start_rejects_an_import_that_already_started(tmp_path):
    source = tmp_path / "dataset.zip"
    source.write_bytes(b"zip")
    upload = _upload(source.name)
    upload.status = JobStatus.uploaded
    upload.final_path = str(source)
    upload.import_status = ImportStatus.pending

    with pytest.raises(HTTPException) as exc_info:
        await start_shapefile_import(upload.id, FakeUploadRepository(upload))

    assert exc_info.value.status_code == 409


def test_status_response_serializes_import_object_with_public_alias():
    response = JobStatusResponse(
        upload_id="upload-1",
        layer_id="layer-1",
        status="uploaded",
        received_bytes=10,
        total_size=10,
        import_process=ShapefileImportStatus(
            status="processing",
            table="dataset_12345678",
            processed_rows=5,
            total_rows=10,
            progress_percent=50,
            tables=[
                ShapefileImportedTable(
                    table="dataset_12345678",
                    geometry_family="polygon",
                    row_count=10,
                )
            ],
        ),
    )

    payload = response.model_dump(by_alias=True)
    assert payload["import"]["schema"] == "geodata"
    assert payload["import"]["table"] == "dataset_12345678"
    assert payload["import"]["progress_percent"] == 50
    assert payload["import"]["tables"] == [
        {
            "schema": "geodata",
            "table": "dataset_12345678",
            "geometry_family": "polygon",
            "row_count": 10,
            "bbox": None,
        }
    ]
