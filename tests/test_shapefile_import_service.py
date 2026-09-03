import os
import shutil
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point
from sqlalchemy import create_engine, text

from app.infrastructure.services.file_service import FileService
from app.infrastructure.services.shapefile_import_service import (
    ShapefileImportError,
    ShapefileValidationError,
    build_import_table_name,
    extract_shapefile_zip,
    drop_geodata_table,
    import_shapefile_to_postgis,
    sanitize_identifier,
)


def _write_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items():
            archive.writestr(name, value)
    return path


def _dataset_members(prefix: str = "nested/Batas Desa") -> dict[str, bytes]:
    return {
        f"{prefix}.shp": b"shp",
        f"{prefix}.dbf": b"dbf",
        f"{prefix}.shx": b"shx",
        f"{prefix}.prj": b"prj",
        f"{prefix}.CPG": b"UTF-8",
    }


def _ensure_geodata_schema(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS geodata"))


def test_build_import_table_name_is_stable_safe_and_unique_by_layer():
    first = build_import_table_name("Batas Desa 2026.zip", "a1b2c3d4-1111-2222")
    second = build_import_table_name("Batas Desa 2026.zip", "ffffffff-1111-2222")

    assert first == "batas_desa_2026_a1b2c3d4"
    assert second == "batas_desa_2026_ffffffff"
    assert len(first) <= 63


def test_sanitize_identifier_handles_reserved_shape_and_numeric_prefix():
    assert sanitize_identifier("123 Nama-Kolom") == "_123_nama_kolom"
    assert sanitize_identifier("!!!", fallback="field") == "field"


def test_extract_accepts_complete_dataset_and_cpg_case(tmp_path):
    archive = _write_zip(tmp_path / "dataset.zip", _dataset_members())

    with extract_shapefile_zip(
        archive,
        max_uncompressed_bytes=1024,
        max_compression_ratio=200,
    ) as datasets:
        assert len(datasets) == 1
        extracted = datasets[0]
        assert extracted.shp_path.name == "Batas Desa.shp"
        assert extracted.shp_path.exists()
        assert extracted.encoding == "UTF-8"

    assert not extracted.shp_path.exists()


@pytest.mark.parametrize(
    "members, expected",
    [
        ({"data.shp": b"x"}, "missing required sidecars"),
        ({"../data.shp": b"x"}, "Unsafe ZIP member path"),
    ],
)
def test_extract_rejects_invalid_archives(tmp_path, members, expected):
    archive = _write_zip(tmp_path / "invalid.zip", members)

    with pytest.raises(ShapefileValidationError, match=expected):
        with extract_shapefile_zip(
            archive,
            max_uncompressed_bytes=1024,
            max_compression_ratio=200,
        ):
            pass


def test_extract_accepts_multiple_complete_shapefiles(tmp_path):
    archive = _write_zip(
        tmp_path / "datasets.zip",
        {**_dataset_members("admin/desa"), **_dataset_members("jalan/jaringan")},
    )

    with extract_shapefile_zip(
        archive,
        max_uncompressed_bytes=2048,
        max_compression_ratio=200,
    ) as datasets:
        assert [dataset.dataset_name for dataset in datasets] == [
            "admin/desa",
            "jalan/jaringan",
        ]
        assert all(dataset.shp_path.exists() for dataset in datasets)


def test_extract_rejects_uncompressed_size_limit(tmp_path):
    archive = _write_zip(tmp_path / "large.zip", _dataset_members() | {"notes.txt": b"x" * 100})

    with pytest.raises(ShapefileValidationError, match="exceeds"):
        with extract_shapefile_zip(
            archive,
            max_uncompressed_bytes=50,
            max_compression_ratio=200,
        ):
            pass


def test_import_rejects_non_postgresql_backend_before_reading_archive(tmp_path):
    archive = _write_zip(tmp_path / "dataset.zip", _dataset_members())
    engine = create_engine("sqlite://")

    with pytest.raises(ShapefileImportError, match="requires PostgreSQL"):
        import_shapefile_to_postgis(
            zip_path=archive,
            engine=engine,
            upload_id="upload-1",
            table_name="dataset_12345678",
            max_uncompressed_bytes=1024,
            max_features=100,
            max_compression_ratio=200,
            batch_size=10,
        )


def test_raw_shp_upload_is_rejected_but_zip_is_supported():
    with pytest.raises(Exception):
        FileService.allowed_file("dataset.shp")
    assert FileService.allowed_file("dataset.zip") == "vector"


def test_postgis_import_end_to_end_when_database_is_configured(tmp_path):
    database_url = os.getenv("TEST_POSTGIS_URL")
    if not database_url:
        pytest.skip("TEST_POSTGIS_URL is not configured")

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    frame = gpd.GeoDataFrame(
        {"Nama Wilayah": ["Utara", "Selatan"], "Jumlah": [10, 20]},
        geometry=[Point(106.8, -6.2), Point(107.0, -6.4)],
        crs="EPSG:4326",
    )
    frame.to_file(source_dir / "Batas Desa.shp")
    archive = Path(shutil.make_archive(str(tmp_path / "dataset"), "zip", source_dir))
    engine = create_engine(database_url)
    _ensure_geodata_schema(engine)
    table_name = "integration_points_12345678"
    progress = []

    try:
        result = import_shapefile_to_postgis(
            zip_path=archive,
            engine=engine,
            upload_id="integration-upload-12345678",
            table_name=table_name,
            max_uncompressed_bytes=10 * 1024 * 1024,
            max_features=100,
            max_compression_ratio=200,
            batch_size=1,
            progress_callback=lambda processed, total: progress.append((processed, total)),
        )

        assert result.row_count == 2
        assert result.datasets[0].geometry_family == "point"
        assert result.datasets[0].target_crs == "EPSG:4326"
        assert progress == [(1, 2), (2, 2)]
        recovered = import_shapefile_to_postgis(
            zip_path=archive,
            engine=engine,
            upload_id="integration-upload-12345678",
            table_name=table_name,
            max_uncompressed_bytes=10 * 1024 * 1024,
            max_features=100,
            max_compression_ratio=200,
            batch_size=1,
        )
        assert recovered.datasets[0].already_existed is True
        assert recovered.row_count == 2
        with engine.connect() as connection:
            assert connection.execute(
                text(f'SELECT COUNT(*) FROM geodata."{table_name}"')
            ).scalar_one() == 2
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM pg_indexes "
                    "WHERE schemaname = 'geodata' AND tablename = :table_name "
                    "AND indexdef ILIKE '%USING gist%'"
                ),
                {"table_name": table_name},
            ).scalar_one() == 1
    finally:
        drop_geodata_table(engine, table_name)
        engine.dispose()


def test_multi_shapefile_zip_imports_each_dataset_when_database_is_configured(tmp_path):
    database_url = os.getenv("TEST_POSTGIS_URL")
    if not database_url:
        pytest.skip("TEST_POSTGIS_URL is not configured")

    source_dir = tmp_path / "multi-source"
    source_dir.mkdir()
    gpd.GeoDataFrame(
        {"nama": ["Desa A", "Desa B"]},
        geometry=[Point(106.8, -6.2), Point(107.0, -6.4)],
        crs="EPSG:4326",
    ).to_file(source_dir / "desa.shp")
    gpd.GeoDataFrame(
        {"nama": ["Jalan A"]},
        geometry=[Point(107.1, -6.3)],
        crs="EPSG:4326",
    ).to_file(source_dir / "jalan.shp")
    archive = Path(shutil.make_archive(str(tmp_path / "multi-dataset"), "zip", source_dir))
    engine = create_engine(database_url)
    _ensure_geodata_schema(engine)
    layer_id = "abcdef12-1111-2222-3333-444444444444"
    expected_tables = [
        build_import_table_name("desa", layer_id),
        build_import_table_name("jalan", layer_id),
    ]

    try:
        result = import_shapefile_to_postgis(
            zip_path=archive,
            engine=engine,
            upload_id="multi-integration-upload-1234",
            layer_id=layer_id,
            max_uncompressed_bytes=10 * 1024 * 1024,
            max_features=100,
            max_compression_ratio=200,
            batch_size=1,
        )

        assert [dataset.table for dataset in result.datasets] == expected_tables
        assert [dataset.row_count for dataset in result.datasets] == [2, 1]
        assert result.row_count == 3
        with engine.connect() as connection:
            for table_name in expected_tables:
                assert connection.execute(
                    text(f'SELECT COUNT(*) FROM geodata."{table_name}"')
                ).scalar_one() > 0
    finally:
        for table_name in expected_tables:
            drop_geodata_table(engine, table_name)
        engine.dispose()
