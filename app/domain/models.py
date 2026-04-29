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
