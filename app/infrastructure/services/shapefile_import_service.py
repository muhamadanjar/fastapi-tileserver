"""Secure, atomic shapefile ZIP import into dynamic PostGIS tables."""

from __future__ import annotations

import math
import re
import shutil
import stat
import tempfile
import unicodedata
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator, Optional

import pandas as pd
import pyogrio
from psycopg2 import sql
from psycopg2.extras import execute_values
from sqlalchemy.engine import Engine


GEODATA_SCHEMA = "geodata"
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_REQUIRED_EXTENSIONS = {".shp", ".dbf", ".shx", ".prj"}
_GEOMETRY_FAMILY = {
    "Point": "point",
    "MultiPoint": "point",
    "LineString": "line",
    "MultiLineString": "line",
    "Polygon": "polygon",
    "MultiPolygon": "polygon",
}


class ShapefileImportError(Exception):
    """Base error for shapefile import failures."""


class ShapefileValidationError(ShapefileImportError):
    """Deterministic source validation failure that should not be retried."""


class ShapefileConfigurationError(ShapefileImportError):
    """Deterministic database configuration failure that should not be retried."""


class ShapefileImportCancelled(ShapefileImportError):
    """Raised cooperatively when an import is cancelled."""


@dataclass(frozen=True)
class ExtractedShapefile:
    shp_path: Path
    dataset_name: str
    encoding: Optional[str]
    uncompressed_bytes: int


@dataclass(frozen=True)
class ShapefileImportResult:
    schema: str
    table: str
    geometry_column: str
    geometry_family: str
    source_crs: str
    target_crs: str
    encoding: Optional[str]
    row_count: int
    bbox: tuple[float, float, float, float]
    column_mapping: dict[str, str]
    already_existed: bool = False

    def metadata(self) -> dict:
        return {
            "schema": self.schema,
            "table": self.table,
            "geometry_column": self.geometry_column,
            "geometry_family": self.geometry_family,
            "source_crs": self.source_crs,
            "target_crs": self.target_crs,
            "encoding": self.encoding,
            "row_count": self.row_count,
            "bbox": list(self.bbox),
            "column_mapping": self.column_mapping,
        }


@dataclass(frozen=True)
class ShapefileArchiveImportResult:
    datasets: tuple[ShapefileImportResult, ...]

    @property
    def row_count(self) -> int:
        return sum(dataset.row_count for dataset in self.datasets)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (
            min(dataset.bbox[0] for dataset in self.datasets),
            min(dataset.bbox[1] for dataset in self.datasets),
            max(dataset.bbox[2] for dataset in self.datasets),
            max(dataset.bbox[3] for dataset in self.datasets),
        )

    @property
    def primary_table(self) -> str:
        return self.datasets[0].table

    def metadata(self) -> dict:
        return {
            "schema": GEODATA_SCHEMA,
            "table": self.primary_table,
            "table_count": len(self.datasets),
            "row_count": self.row_count,
            "bbox": list(self.bbox),
            "datasets": [dataset.metadata() for dataset in self.datasets],
        }


def sanitize_identifier(value: str, *, fallback: str = "field", max_length: int = 63) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", normalized).strip("_").lower()
    normalized = re.sub(r"_+", "_", normalized)
    if not normalized:
        normalized = fallback
    if normalized[0].isdigit():
        normalized = f"_{normalized}"
    return normalized[:max_length].rstrip("_") or fallback


def build_import_table_name(filename: str, layer_id: str) -> str:
    stem = Path(filename).stem
    suffix = sanitize_identifier(layer_id.replace("-", ""), fallback="layer")[:8]
    base_max = 63 - len(suffix) - 1
    base = sanitize_identifier(stem, fallback="shapefile", max_length=base_max)
    return f"{base}_{suffix}"


def staging_table_name(upload_id: str, dataset_index: Optional[int] = None) -> str:
    compact = sanitize_identifier(upload_id.replace("-", ""), fallback="upload", max_length=44)
    suffix = "" if dataset_index is None else f"_{dataset_index + 1}"
    return f"_import_{compact}{suffix}"


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_IFMT(mode) == stat.S_IFLNK


def _safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ShapefileValidationError(f"Unsafe ZIP member path: {name!r}")
    return path


def _read_cpg(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        value = path.read_text(encoding="ascii").strip()
    except UnicodeDecodeError as exc:
        raise ShapefileValidationError("The .cpg file must contain an ASCII encoding name") from exc
    return value or None


@contextmanager
def extract_shapefile_zip(
    zip_path: Path,
    *,
    max_uncompressed_bytes: int,
    max_compression_ratio: int,
) -> Iterator[tuple[ExtractedShapefile, ...]]:
    if zip_path.suffix.lower() != ".zip" or not zipfile.is_zipfile(zip_path):
        raise ShapefileValidationError("Shapefile input must be a valid ZIP archive")

    with zipfile.ZipFile(zip_path) as archive:
        files = [entry for entry in archive.infolist() if not entry.is_dir()]
        if not files:
            raise ShapefileValidationError("ZIP archive is empty")

        safe_paths: dict[str, tuple[zipfile.ZipInfo, PurePosixPath]] = {}
        total_size = 0
        for entry in files:
            member = _safe_member_path(entry.filename)
            if _is_symlink(entry):
                raise ShapefileValidationError(f"ZIP symlinks are not allowed: {entry.filename!r}")
            if entry.flag_bits & 0x1:
                raise ShapefileValidationError("Encrypted ZIP entries are not allowed")
            total_size += entry.file_size
            if total_size > max_uncompressed_bytes:
                raise ShapefileValidationError(
                    f"Uncompressed archive exceeds {max_uncompressed_bytes} bytes"
                )
            if entry.file_size >= 1_048_576:
                ratio = entry.file_size / max(entry.compress_size, 1)
                if ratio > max_compression_ratio:
                    raise ShapefileValidationError(
                        f"Suspicious ZIP compression ratio for {entry.filename!r}"
                    )
            key = member.as_posix().lower()
            if key in safe_paths:
                raise ShapefileValidationError(f"Duplicate ZIP member: {entry.filename!r}")
            safe_paths[key] = (entry, member)

        shp_members = sorted(
            (
                (entry, member)
                for entry, member in safe_paths.values()
                if member.suffix.lower() == ".shp"
            ),
            key=lambda item: item[1].as_posix().lower(),
        )
        if not shp_members:
            raise ShapefileValidationError("ZIP must contain at least one .shp file")

        dataset_bases: list[str] = []
        for _, shp_member in shp_members:
            dataset_base = shp_member.with_suffix("").as_posix().lower()
            available = {
                member.suffix.lower()
                for _, member in safe_paths.values()
                if member.with_suffix("").as_posix().lower() == dataset_base
            }
            missing = sorted(_REQUIRED_EXTENSIONS - available)
            if missing:
                raise ShapefileValidationError(
                    f"Shapefile {shp_member.as_posix()!r} is missing required sidecars: "
                    f"{', '.join(missing)}"
                )
            dataset_bases.append(dataset_base)

        with tempfile.TemporaryDirectory(prefix="shp_import_") as temp_dir:
            root = Path(temp_dir)
            for entry, member in safe_paths.values():
                destination = root.joinpath(*member.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)

            extracted: list[ExtractedShapefile] = []
            for (_, shp_member), dataset_base in zip(shp_members, dataset_bases):
                extracted_shp = root.joinpath(*shp_member.parts)
                cpg_path = next(
                    (
                        root.joinpath(*member.parts)
                        for _, member in safe_paths.values()
                        if member.with_suffix("").as_posix().lower() == dataset_base
                        and member.suffix.lower() == ".cpg"
                    ),
                    extracted_shp.with_suffix(".cpg"),
                )
                extracted.append(
                    ExtractedShapefile(
                        shp_path=extracted_shp,
                        dataset_name=shp_member.with_suffix("").as_posix(),
                        encoding=_read_cpg(cpg_path),
                        uncompressed_bytes=total_size,
                    )
                )
            yield tuple(extracted)


def _unique_column_mapping(fields: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used = {"id", "geom"}
    for original in fields:
        base = sanitize_identifier(original, fallback="field")
        candidate = base
        counter = 2
        while candidate in used:
            suffix = f"_{counter}"
            candidate = f"{base[:63 - len(suffix)]}{suffix}"
            counter += 1
        mapping[original] = candidate
        used.add(candidate)
    return mapping


def _postgres_type(dtype: str) -> str:
    value = dtype.lower()
    if "bool" in value:
        return "BOOLEAN"
    if "int" in value:
        return "BIGINT"
    if "float" in value or "double" in value or "real" in value:
        return "DOUBLE PRECISION"
    if "datetime" in value or "timestamp" in value:
        return "TIMESTAMP"
    if value == "date":
        return "DATE"
    return "TEXT"


def _python_value(value):
    if value is None:
        return None
    try:
        missing = pd.isna(value)
        if bool(missing):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, (str, bool, int, float, date, datetime)):
        return value
    return str(value)


def _assert_postgis(engine: Engine, cursor) -> None:
    if engine.dialect.name != "postgresql":
        raise ShapefileConfigurationError("Shapefile import requires PostgreSQL with PostGIS")
    try:
        cursor.execute("SELECT PostGIS_Version()")
        cursor.fetchone()
    except Exception as exc:
        raise ShapefileConfigurationError("PostGIS extension is not installed or accessible") from exc


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute("SELECT to_regclass(%s)", (f"{GEODATA_SCHEMA}.{table_name}",))
    return cursor.fetchone()[0] is not None


def _existing_result(cursor, table_name: str) -> ShapefileImportResult:
    identifier = sql.SQL("{}.{}").format(sql.Identifier(GEODATA_SCHEMA), sql.Identifier(table_name))
    cursor.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(identifier))
    row_count = int(cursor.fetchone()[0])
    cursor.execute(
        sql.SQL(
            "SELECT ST_XMin(extent), ST_YMin(extent), ST_XMax(extent), ST_YMax(extent) "
            "FROM (SELECT ST_Extent(geom) AS extent FROM {}) AS bounds"
        ).format(identifier)
    )
    bbox_row = cursor.fetchone()
    cursor.execute(sql.SQL("SELECT GeometryType(geom) FROM {} LIMIT 1").format(identifier))
    geometry_type = cursor.fetchone()[0]
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
        (GEODATA_SCHEMA, table_name),
    )
    fields = [row[0] for row in cursor.fetchall() if row[0] not in {"id", "geom"}]
    family = _GEOMETRY_FAMILY.get(geometry_type, geometry_type.lower())
    return ShapefileImportResult(
        schema=GEODATA_SCHEMA,
        table=table_name,
        geometry_column="geom",
        geometry_family=family,
        source_crs="unknown (recovered existing table)",
        target_crs="EPSG:4326",
        encoding=None,
        row_count=row_count,
        bbox=tuple(float(value) for value in bbox_row),
        column_mapping={field: field for field in fields},
        already_existed=True,
    )


def _validate_identifier(table_name: str) -> None:
    if not _IDENTIFIER_RE.fullmatch(table_name) or len(table_name) > 63:
        raise ValueError(f"Unsafe database identifier: {table_name!r}")


def drop_geodata_table(engine: Engine, table_name: str) -> None:
    drop_geodata_tables(engine, [table_name])


def drop_geodata_tables(engine: Engine, table_names: list[str]) -> None:
    for table_name in table_names:
        _validate_identifier(table_name)
    with engine.begin() as connection:
        for table_name in table_names:
            connection.exec_driver_sql(
                f'DROP TABLE IF EXISTS "{GEODATA_SCHEMA}"."{table_name}"'
            )


def drop_import_staging_table(engine: Engine, upload_id: str) -> None:
    prefix = staging_table_name(upload_id)
    raw_connection = engine.raw_connection()
    try:
        cursor = raw_connection.cursor()
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND (table_name = %s OR table_name LIKE %s)",
            (GEODATA_SCHEMA, prefix, f"{prefix}_%"),
        )
        for (table_name,) in cursor.fetchall():
            _validate_identifier(table_name)
            cursor.execute(
                sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                    sql.Identifier(GEODATA_SCHEMA), sql.Identifier(table_name)
                )
            )
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        raw_connection.close()


def import_shapefile_to_postgis(
    *,
    zip_path: Path,
    engine: Engine,
    upload_id: str,
    table_name: Optional[str] = None,
    layer_id: Optional[str] = None,
    max_uncompressed_bytes: int,
    max_features: int,
    max_compression_ratio: int,
    batch_size: int,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> ShapefileArchiveImportResult:
    if not table_name and not layer_id:
        raise ValueError("table_name or layer_id is required")
    if table_name:
        _validate_identifier(table_name)
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    raw_connection = engine.raw_connection()
    stage_names: list[str] = []
    try:
        cursor = raw_connection.cursor()
        _assert_postgis(engine, cursor)

        with extract_shapefile_zip(
            Path(zip_path),
            max_uncompressed_bytes=max_uncompressed_bytes,
            max_compression_ratio=max_compression_ratio,
        ) as extracted_datasets:
            final_names: list[str] = []
            used_names: set[str] = set()
            for index, extracted in enumerate(extracted_datasets):
                candidate = (
                    table_name
                    if len(extracted_datasets) == 1 and table_name
                    else build_import_table_name(extracted.dataset_name, layer_id or table_name or upload_id)
                )
                base = candidate
                collision_index = 2
                while candidate in used_names:
                    suffix = f"_{collision_index}"
                    candidate = f"{base[:63 - len(suffix)]}{suffix}"
                    collision_index += 1
                _validate_identifier(candidate)
                used_names.add(candidate)
                final_names.append(candidate)

            existing = [_table_exists(cursor, name) for name in final_names]
            if all(existing):
                return ShapefileArchiveImportResult(
                    tuple(_existing_result(cursor, name) for name in final_names)
                )
            if any(existing):
                conflicts = [name for name, exists in zip(final_names, existing) if exists]
                raise ShapefileConfigurationError(
                    f"Some target tables already exist: {', '.join(conflicts)}"
                )

            dataset_info: list[tuple[ExtractedShapefile, dict, dict, int]] = []
            archive_total = 0
            for extracted in extracted_datasets:
                info_kwargs = {"encoding": extracted.encoding} if extracted.encoding else {}
                try:
                    info = pyogrio.read_info(extracted.shp_path, **info_kwargs)
                except UnicodeDecodeError:
                    info_kwargs = {"encoding": "UTF-8"}
                    info = pyogrio.read_info(extracted.shp_path, **info_kwargs)
                total = int(info.get("features") or 0)
                if total <= 0:
                    raise ShapefileValidationError(
                        f"Shapefile {extracted.dataset_name!r} contains no features"
                    )
                archive_total += total
                dataset_info.append((extracted, info_kwargs, info, total))

            if archive_total > max_features:
                raise ShapefileValidationError(
                    f"Archive contains {archive_total} features; maximum is {max_features}"
                )

            results: list[ShapefileImportResult] = []
            archive_processed = 0
            for dataset_index, ((extracted, info_kwargs, info, total), final_name) in enumerate(
                zip(dataset_info, final_names)
            ):
                source_crs = info.get("crs")
                if not source_crs:
                    raise ShapefileValidationError(
                        f"Shapefile {extracted.dataset_name!r} CRS is missing or unreadable"
                    )
                fields = [str(field) for field in info.get("fields", [])]
                dtypes = [str(dtype) for dtype in info.get("dtypes", [])]
                if len(fields) != len(dtypes):
                    raise ShapefileValidationError(
                        f"Shapefile {extracted.dataset_name!r} field metadata is inconsistent"
                    )
                column_mapping = _unique_column_mapping(fields)
                column_defs = [
                    sql.SQL("{} {}").format(
                        sql.Identifier(column_mapping[field]), sql.SQL(_postgres_type(dtype))
                    )
                    for field, dtype in zip(fields, dtypes)
                ]

                stage_name = staging_table_name(
                    upload_id, dataset_index if len(extracted_datasets) > 1 else None
                )
                stage_names.append(stage_name)
                stage_identifier = sql.SQL("{}.{}").format(
                    sql.Identifier(GEODATA_SCHEMA), sql.Identifier(stage_name)
                )
                cursor.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(stage_identifier))
                definitions = [
                    sql.SQL("id BIGSERIAL PRIMARY KEY"),
                    *column_defs,
                    sql.SQL("geom geometry(Geometry, 4326) NOT NULL"),
                ]
                cursor.execute(
                    sql.SQL("CREATE TABLE {} ({})").format(
                        stage_identifier, sql.SQL(", ").join(definitions)
                    )
                )
                raw_connection.commit()

                geometry_family: Optional[str] = None
                minx = miny = math.inf
                maxx = maxy = -math.inf
                processed = 0
                actual_encoding = extracted.encoding or info.get("encoding") or info_kwargs.get("encoding")

                for offset in range(0, total, batch_size):
                    frame = pyogrio.read_dataframe(
                        extracted.shp_path,
                        skip_features=offset,
                        max_features=min(batch_size, total - offset),
                        **info_kwargs,
                    )
                    if frame.empty:
                        raise ShapefileValidationError(
                            f"Unexpected empty batch in {extracted.dataset_name!r} at feature offset {offset}"
                        )
                    if frame.crs is None:
                        raise ShapefileValidationError(
                            f"Shapefile {extracted.dataset_name!r} CRS is missing or unreadable"
                        )
                    frame = frame.to_crs("EPSG:4326")

                    invalid = frame.geometry.isna() | frame.geometry.is_empty | ~frame.geometry.is_valid
                    if invalid.any():
                        examples = [
                            offset + position
                            for position in range(len(frame))
                            if invalid.iloc[position]
                        ][:5]
                        raise ShapefileValidationError(
                            f"Invalid or empty geometries in {extracted.dataset_name!r} "
                            f"({int(invalid.sum())}); example indexes: {examples}"
                        )

                    geometry_types = frame.geometry.geom_type.unique()
                    families = {_GEOMETRY_FAMILY.get(value) for value in geometry_types}
                    if None in families or len(families) != 1:
                        raise ShapefileValidationError(
                            f"Mixed or unsupported geometry families in {extracted.dataset_name!r}: "
                            f"{sorted(str(value) for value in geometry_types)}"
                        )
                    batch_family = families.pop()
                    if geometry_family is not None and geometry_family != batch_family:
                        raise ShapefileValidationError(
                            f"Mixed geometry families in {extracted.dataset_name!r}: "
                            f"{geometry_family} and {batch_family}"
                        )
                    geometry_family = batch_family

                    bounds = frame.total_bounds
                    minx, miny = min(minx, bounds[0]), min(miny, bounds[1])
                    maxx, maxy = max(maxx, bounds[2]), max(maxy, bounds[3])

                    insert_columns = [sql.Identifier(column_mapping[field]) for field in fields]
                    insert_columns.append(sql.Identifier("geom"))
                    insert_sql = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
                        stage_identifier, sql.SQL(", ").join(insert_columns)
                    ).as_string(cursor)
                    template_values = (["%s"] * len(fields)) + [
                        "ST_SetSRID(ST_GeomFromWKB(%s), 4326)"
                    ]
                    template = f"({', '.join(template_values)})"
                    rows = [
                        (
                            *[_python_value(row.get(field)) for field in fields],
                            bytes(row.geometry.wkb),
                        )
                        for _, row in frame.iterrows()
                    ]
                    execute_values(cursor, insert_sql, rows, template=template, page_size=batch_size)
                    raw_connection.commit()

                    processed += len(frame)
                    if progress_callback:
                        progress_callback(archive_processed + processed, archive_total)

                archive_processed += processed
                index_name = sanitize_identifier(f"{final_name}_geom_gix")
                cursor.execute(
                    sql.SQL("CREATE INDEX {} ON {} USING GIST (geom)").format(
                        sql.Identifier(index_name), stage_identifier
                    )
                )
                cursor.execute(sql.SQL("ANALYZE {}").format(stage_identifier))
                raw_connection.commit()
                results.append(
                    ShapefileImportResult(
                        schema=GEODATA_SCHEMA,
                        table=final_name,
                        geometry_column="geom",
                        geometry_family=geometry_family or "unknown",
                        source_crs=str(source_crs),
                        target_crs="EPSG:4326",
                        encoding=str(actual_encoding) if actual_encoding else None,
                        row_count=processed,
                        bbox=(float(minx), float(miny), float(maxx), float(maxy)),
                        column_mapping=column_mapping,
                    )
                )

            for stage_name, final_name in zip(stage_names, final_names):
                cursor.execute(
                    sql.SQL("ALTER TABLE {}.{} RENAME TO {}").format(
                        sql.Identifier(GEODATA_SCHEMA),
                        sql.Identifier(stage_name),
                        sql.Identifier(final_name),
                    )
                )
            raw_connection.commit()
            return ShapefileArchiveImportResult(tuple(results))
    except Exception:
        raw_connection.rollback()
        try:
            cursor = raw_connection.cursor()
            for stage_name in stage_names:
                cursor.execute(
                    sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                        sql.Identifier(GEODATA_SCHEMA), sql.Identifier(stage_name)
                    )
                )
            raw_connection.commit()
        except Exception:
            raw_connection.rollback()
        raise
    finally:
        raw_connection.close()
