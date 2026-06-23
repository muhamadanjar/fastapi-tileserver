from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime


class TilingJobRequest(BaseModel):
    file_type: str
    layer_id: str


class TilingJobResponse(BaseModel):
    message: str
    upload_id: str
    file_type: str
    layer_id: str
    tile_url_template: Optional[str] = None


class LayerInfo(BaseModel):
    id: str
    name: str
    type: str
    path: str


class UploadInitRequest(BaseModel):
    filename: str
    total_size: int
    output_format: str = "raster"
    max_zoom: Optional[int] = None


class UploadInitResponse(BaseModel):
    upload_id: str
    layer_id: str
    message: str
    chunk_size: int
    total_chunks: int


class ChunkUploadResponse(BaseModel):
    upload_id: str
    received_bytes: int
    total_size: int
    uploaded_chunks: int
    total_chunks: int
    progress_percent: float
    is_complete: bool
    layer_id: Optional[str] = None
    tile_url_template: Optional[str] = None


class JobStatusResponse(BaseModel):
    upload_id: str
    layer_id: str
    status: str
    received_bytes: int
    total_size: int
    uploaded_chunks: int = 0
    total_chunks: int = 0
    progress_percent: float = 0.0
    chunk_map: Optional[Dict[str, int]] = None
    error_message: Optional[str] = None
    tile_url_template: Optional[str] = None
    bbox: Optional[list[float]] = None


class LayerResponse(BaseModel):
    id: str
    upload_session_id: Optional[str] = None
    code: Optional[str] = None
    layer_type: str = "tile"
    filename: str
    file_type: str
    tile_url_template: str
    status: str = "done"
    created_at: datetime
    bbox: Optional[list[float]] = None
    file_metadata: Optional[dict] = None
    abstract: Optional[str] = None
    topic_category: Optional[str] = None
    language: Optional[str] = None


class PatchLayerRequest(BaseModel):
    file_metadata: Optional[dict] = None
    filename: Optional[str] = None
    layer_type: Optional[str] = None
    tile_url_template: Optional[str] = None
    refresh_bbox: bool = False
    abstract: Optional[str] = None
    topic_category: Optional[str] = None
    language: Optional[str] = None


class LayerFieldsResponse(BaseModel):
    layer_id: str
    fields: list[str]


class ExternalLayerRequest(BaseModel):
    layer_type: str
    filename: str
    source_url: str
    params: Optional[dict] = None
    bbox: Optional[list[float]] = None


class FeatureQueryResponse(BaseModel):
    type: str
    count: int
    features: Optional[list[dict]] = None
    values: Optional[dict[str, float]] = None


class FieldUniqueValuesResponse(BaseModel):
    layer_id: str
    field_name: str
    values: list[str]


class BboxFeaturesResponse(BaseModel):
    layer_id: str
    count: int
    exceeded: bool
    features: list[dict[str, Any]]
