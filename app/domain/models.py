import enum
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class JobStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Layer(SQLModel, table=True):
    __tablename__ = "layers"

    id: str = Field(primary_key=True)
    upload_session_id: str = Field(foreign_key="upload_sessions.id")
    filename: str
    file_type: str
    tile_url_template: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    bbox_west: Optional[float] = Field(default=None)
    bbox_south: Optional[float] = Field(default=None)
    bbox_east: Optional[float] = Field(default=None)
    bbox_north: Optional[float] = Field(default=None)
