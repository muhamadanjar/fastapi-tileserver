import enum
from datetime import datetime, timezone
from typing import Dict, Optional, Any
from sqlalchemy import DateTime, Text
from sqlmodel import SQLModel, Field, Column, JSON


class JobStatus(str, enum.Enum):
    pending = "pending"
    uploaded = "uploaded"
    uploading = "uploading"
    paused = "paused"
    processing = "processing"
    done = "done"
    failed = "failed"
    expired = "expired"
    cancelled = "cancelled"


class AnalysisReference(SQLModel, table=True):
    __tablename__ = "analysis_references"
    layer_id: str = Field(primary_key=True, foreign_key="layers.id")
    name: str
    category_field: str
    attributes: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True), nullable=False))


class AnalysisUpload(SQLModel, table=True):
    __tablename__ = "analysis_uploads"
    id: str = Field(primary_key=True)
    owner_hash: str = Field(index=True)
    filename: str
    feature_count: int
    geometry_types: list[str] = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    expires_at: datetime = Field(index=True, sa_type=DateTime(timezone=True))


class ReferenceAnalysisJob(SQLModel, table=True):
    __tablename__ = "reference_analysis_jobs"
    id: str = Field(primary_key=True)
    input_id: str = Field(foreign_key="analysis_uploads.id", unique=True)
    owner_hash: str = Field(index=True)
    reference_id: str  # Historical identity survives deletion of the source.
    reference_config: dict = Field(sa_column=Column(JSON, nullable=False))
    operation: str = Field(default="intersect")
    status: str = Field(default="pending", index=True)
    task_id: str
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    started_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    completed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    expires_at: Optional[datetime] = Field(default=None, index=True, sa_type=DateTime(timezone=True))
    error: Optional[str] = None
    result_count: int = 0
    source_version: Optional[str] = None


class ActiveAnalysisSource(SQLModel, table=True):
    __tablename__ = "active_analysis_sources"
    job_id: str = Field(primary_key=True, foreign_key="reference_analysis_jobs.id")
    layer_id: str = Field(foreign_key="layers.id", index=True)


class ImportStatus(str, enum.Enum):
    not_applicable = "not_applicable"
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class LayerType(str, enum.Enum):
    tile = "tile"
    mvt = "mvt"
    vector = "vector"
    shp = "shp"
    wms = "wms"
    wfs = "wfs"
    wmts = "wmts"
    geojson = "geojson"
    kml = "kml"
    esri_mapserver = "esri_mapserver"
    esri_featureserver = "esri_featureserver"
    esri_tileserver = "esri_tileserver"
    esri_vectortileserver = "esri_vectortileserver"
    esri_imageserver = "esri_imageserver"
    postgis = "postgis"




class UploadSession(SQLModel, table=True):
    __tablename__ = "upload_sessions"

    id: str = Field(primary_key=True)
    filename: str
    file_type: str
    layer_id: str
    total_size: int
    received_bytes: int = Field(default=0)
    status: str = Field(default=JobStatus.pending)
    error_message: Optional[str] = Field(default=None)
    final_path: Optional[str] = Field(default=None)
    output_format: str = Field(default="raster")
    max_zoom: Optional[int] = Field(default=None)
    chunk_map: Optional[Dict[str, int]] = Field(default_factory=dict, sa_column=Column(JSON))
    total_chunks: int = Field(default=0)
    uploaded_chunks: int = Field(default=0)
    chunk_size: int = Field(default=0)
    celery_task_id: Optional[str] = Field(default=None)
    artifact_id: Optional[str] = Field(default=None, index=True)
    artifact_lease_id: Optional[str] = Field(default=None)
    artifact_handoff_id: Optional[str] = Field(default=None, unique=True, index=True)
    pending_release: bool = Field(default=False)
    released_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    import_status: str = Field(default=ImportStatus.not_applicable)
    import_task_id: Optional[str] = Field(default=None)
    import_error: Optional[str] = Field(default=None, sa_column=Column(Text()))
    import_table_name: Optional[str] = Field(default=None)
    import_processed_rows: int = Field(default=0)
    import_total_rows: int = Field(default=0)
    imported_row_count: Optional[int] = Field(default=None)
    imported_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    expires_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))


class Layer(SQLModel, table=True):
    __tablename__ = "layers"

    id: str = Field(primary_key=True)
    upload_session_id: Optional[str] = Field(default=None, foreign_key="upload_sessions.id")
    code: Optional[str] = Field(default=None)
    layer_type: str = Field(default=LayerType.tile)
    filename: str
    file_type: str
    tile_url_template: str
    is_active: bool = Field(default=False)
    is_visible: bool = Field(default=False)
    opacity: float = Field(default=1.0)
    sorting: int = Field(default=0)
    file_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="Additional metadata about the file in JSON format"
    )

    abstract: Optional[str] = Field(default=None, sa_column=Column(Text()))
    topic_category: Optional[str] = Field(default=None, max_length=64)
    language: Optional[str] = Field(default="eng", max_length=8)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
    bbox_west: Optional[float] = Field(default=None)
    bbox_south: Optional[float] = Field(default=None)
    bbox_east: Optional[float] = Field(default=None)
    bbox_north: Optional[float] = Field(default=None)
    mbtiles_path: Optional[str] = Field(default=None)
    mbtiles_status: Optional[str] = Field(default=None)
    mbtiles_size_bytes: Optional[int] = Field(default=None)


class GeometryType(str, enum.Enum):
    point = "point"
    line = "line"
    polygon = "polygon"


class OverlayOperation(str, enum.Enum):
    intersection = "intersection"
    union = "union"
    dissolve = "dissolve"
    clip = "clip"
    difference = "difference"
    buffer = "buffer"
    sym_difference = "sym_difference"
    simplify = "simplify"
    spatial_join = "spatial_join"
    centroid = "centroid"


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: str = Field(primary_key=True)
    name: str
    description: Optional[str] = Field(default=None, sa_column=Column(Text()))
    geometry_type: str  # GeometryType value
    form_schema: list = Field(default_factory=list, sa_column=Column(JSON))
    layer_id: Optional[str] = Field(default=None, foreign_key="layers.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))


class Feature(SQLModel, table=True):
    __tablename__ = "features"

    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    geometry: Dict[str, Any] = Field(sa_column=Column(JSON))
    attributes: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_by: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))


class AnalysisResult(SQLModel, table=True):
    __tablename__ = "analysis_results"

    id: str = Field(primary_key=True)
    layer_id: str = Field(foreign_key="layers.id", index=True)
    operation: str  # OverlayOperation value
    input_layer_a_id: str
    input_layer_b_id: Optional[str] = None
    output_name: Optional[str] = None
    feature_count: int = Field(default=0)
    skipped_null_geometry: int = Field(default=0)
    warning: Optional[str] = Field(default=None, sa_column=Column(Text()))
    result_file_path: Optional[str] = None
    ephemeral: bool = Field(default=True)
    status: str = Field(default="done")  # pending|processing|done|failed
    celery_task_id: Optional[str] = Field(default=None)
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text()))
    bbox_west: Optional[float] = Field(default=None)
    bbox_south: Optional[float] = Field(default=None)
    bbox_east: Optional[float] = Field(default=None)
    bbox_north: Optional[float] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))


class Attachment(SQLModel, table=True):
    __tablename__ = "attachments"

    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    feature_id: Optional[str] = Field(default=None, index=True)
    filename: str
    stored_path: str
    content_type: Optional[str] = Field(default=None)
    size_bytes: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))


# --- Multi-SHP Batch Processing & Layer Groups ---

class BatchRecord(SQLModel, table=True):
    """A batch of datasets extracted from a single ZIP upload."""
    __tablename__ = "batches"

    id: str = Field(primary_key=True)
    upload_id: str = Field(foreign_key="upload_sessions.id", index=True)
    filename: str
    status: str = Field(default="inspecting")  # inspecting|inspecting_running|ready|pending|processing|done|failed|cancelled|inspection_failed
    source_digest: str = Field(default="")
    mode: str = Field(default="separate")  # separate|group
    output_format: str = Field(default="raster")  # raster|mvt|wms
    max_zoom: int = Field(default=14)
    group_id: Optional[str] = Field(default=None, index=True)
    task_token: str = Field(default="")
    error: Optional[str] = Field(default=None, sa_column=Column(Text()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))


class DatasetRecord(SQLModel, table=True):
    """One SHP dataset detected inside a batch's ZIP."""
    __tablename__ = "datasets"

    id: str = Field(primary_key=True)
    batch_id: str = Field(foreign_key="batches.id", index=True)
    path: str
    name: str
    valid: bool = Field(default=True)
    error: Optional[str] = Field(default=None, sa_column=Column(Text()))
    geometry: str = Field(default="")
    feature_count: int = Field(default=0)
    bbox: Optional[list] = Field(default=None, sa_column=Column(JSON))
    style: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    selected: bool = Field(default=False)
    layer_id: Optional[str] = Field(default=None, index=True)
    code: str = Field(default="")
    visible: bool = Field(default=True)
    status: str = Field(default="detected")  # detected|pending|processing|done|failed|cancelled
    progress: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))


class GroupRecord(SQLModel, table=True):
    """A named composition of independent layers."""
    __tablename__ = "layer_groups"

    id: str = Field(primary_key=True)
    code: str = Field(unique=True, index=True)
    name: str
    output_format: str
    status: str = Field(default="draft")  # draft|published|failed
    revision: int = Field(default=0)
    error: Optional[str] = Field(default=None, sa_column=Column(Text()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))


class GroupMemberRecord(SQLModel, table=True):
    """Membership entry linking a layer to a group."""
    __tablename__ = "layer_group_members"

    id: str = Field(primary_key=True)
    group_id: str = Field(foreign_key="layer_groups.id", index=True)
    layer_id: str = Field(index=True)
    visible: bool = Field(default=True)
    sorting: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))


class CodeReservation(SQLModel, table=True):
    """Ensures uniqueness of layer and group codes."""
    __tablename__ = "code_reservations"

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)
    owner: str  # layer_id or group_id
