import enum
from datetime import datetime, timezone
from typing import Dict, Optional, Any
from sqlalchemy import DateTime
from sqlmodel import SQLModel, Field, Column, JSON


class JobStatus(str, enum.Enum):
    pending = "pending"
    uploading = "uploading"
    paused = "paused"
    processing = "processing"
    done = "done"
    failed = "failed"
    expired = "expired"

class LayerType(str, enum.Enum):
    tile = "tile"
    mvt = "mvt"
    vector = "vector"
    wms = "wms"
    wfs = "wfs"
    wmts = "wmts"
    esri_mapserver = "esri_mapserver"
    esri_featureserver = "esri_featureserver"
    esri_tileserver = "esri_tileserver"
    esri_vectortileserver = "esri_vectortileserver"
    esri_imageserver = "esri_imageserver"




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

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
    bbox_west: Optional[float] = Field(default=None)
    bbox_south: Optional[float] = Field(default=None)
    bbox_east: Optional[float] = Field(default=None)
    bbox_north: Optional[float] = Field(default=None)
