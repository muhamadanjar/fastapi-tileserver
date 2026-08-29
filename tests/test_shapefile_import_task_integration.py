import os
import shutil
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point

from app.domain.models import ImportStatus, JobStatus, Layer, UploadSession
from app.infrastructure.db.connection import db
from app.infrastructure.services.shapefile_import_service import (
    build_import_table_name,
    drop_geodata_table,
)
from app.workers.tasks import import_shapefile_task


def test_celery_task_updates_upload_and_registers_layer(tmp_path):
    database_url = os.getenv("TEST_POSTGIS_URL")
    if not database_url:
        pytest.skip("TEST_POSTGIS_URL is not configured")
    if db.config.get_database_url(sync=True) != database_url:
        pytest.skip("DATABASE_URL must match TEST_POSTGIS_URL for task integration")

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    gpd.GeoDataFrame(
        {"nama": ["A", "B"]},
        geometry=[Point(106.8, -6.2), Point(107.0, -6.4)],
        crs="EPSG:4326",
    ).to_file(source_dir / "wilayah.shp")
    archive = Path(shutil.make_archive(str(tmp_path / "wilayah"), "zip", source_dir))

    upload_id = "integration-task-upload"
    layer_id = "12345678-1111-2222-3333-444455556666"
    table_name = build_import_table_name(archive.name, layer_id)
    with db.get_session() as session:
        session.add(
            UploadSession(
                id=upload_id,
                filename=archive.name,
                file_type="vector",
                layer_id=layer_id,
                total_size=archive.stat().st_size,
                received_bytes=archive.stat().st_size,
                status=JobStatus.uploaded,
                final_path=str(archive),
                import_status=ImportStatus.pending,
                import_task_id="integration-task-id",
                import_table_name=table_name,
            )
        )

    try:
        task_result = import_shapefile_task.apply(
            kwargs={"upload_id": upload_id},
            task_id="integration-task-id",
            throw=True,
        )
        assert task_result.successful()

        with db.get_session() as session:
            upload = session.get(UploadSession, upload_id)
            layer = session.get(Layer, layer_id)
            assert upload.import_status == ImportStatus.completed
            assert upload.imported_row_count == 2
            assert layer.layer_type == "postgis"
            assert layer.file_metadata["postgis"]["table"] == table_name
            assert layer.file_metadata["postgis"]["row_count"] == 2
    finally:
        drop_geodata_table(db.get_engine(), table_name)
        with db.get_session() as session:
            layer = session.get(Layer, layer_id)
            if layer:
                session.delete(layer)
                session.commit()
            upload = session.get(UploadSession, upload_id)
            if upload:
                session.delete(upload)

