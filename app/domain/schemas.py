from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class TilingJobRequest(BaseModel):
    file_type: str
    layer_id: str


class TilingJobResponse(BaseModel):
    message: str
    upload_id: str
    file_type: str
    layer_id: str
    tile_url_template: str


class LayerInfo(BaseModel):
    id: str
    name: str
    type: str
    path: str


class UploadInitRequest(BaseModel):
    filename: str
    total_size: int


class UploadInitResponse(BaseModel):
    upload_id: str
    layer_id: str
    message: str
    chunk_size: int


class ChunkUploadResponse(BaseModel):
    upload_id: str
    received_bytes: int
    total_size: int
    is_complete: bool
    layer_id: Optional[str] = None
    tile_url_template: Optional[str] = None


class JobStatusResponse(BaseModel):
    upload_id: str
    layer_id: str
    status: str
    received_bytes: int
    total_size: int
    error_message: Optional[str] = None
    tile_url_template: Optional[str] = None
    bbox: Optional[list[float]] = None


class LayerResponse(BaseModel):
    id: str
    upload_session_id: str
    filename: str
    file_type: str
    tile_url_template: str
    created_at: datetime
    bbox: Optional[list[float]] = None


class FeatureQueryResponse(BaseModel):
    type: str
    count: int
    features: Optional[list[dict]] = None
    values: Optional[dict[str, float]] = None
