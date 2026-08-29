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
