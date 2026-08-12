from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Literal
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


class ArtifactTilingRequest(BaseModel):
    artifact_id: str = Field(min_length=36, max_length=36)
    grant_id: str = Field(min_length=36, max_length=36)
    handoff_id: str = Field(min_length=8, max_length=255)
    output_format: Literal["raster", "mvt"] = "raster"
    max_zoom: Optional[int] = None


class ArtifactTilingResponse(BaseModel):
    upload_id: str
    layer_id: str
    artifact_id: str
    status: str
    task_id: str


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


class LayerStyleRequest(BaseModel):
    mode: Literal["simple", "sld"]
    style: Optional[dict] = None      # required when mode=simple; geometry-keyed JSON
    sld_body: Optional[str] = None    # required when mode=sld; raw SLD XML


class LayerStyleResponse(BaseModel):
    layer_id: str
    style_name: str
    style: Optional[dict] = None      # stored editor state incl. mode, None if never styled


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


# --- Esri Discovery ---

class EsriDiscoverRequest(BaseModel):
    url: str
    proxy_url: str = ""
    token: str = ""


class EsriDiscoverLayerInfo(BaseModel):
    id: int
    name: str
    geometry_type: str
    query_supported: bool


class EsriDiscoverResponse(BaseModel):
    service_type: str  # MapServer, FeatureServer, etc.
    service_url: str
    layers: list[EsriDiscoverLayerInfo]
    render_only: bool
    skipped: list[dict[str, Any]]


# --- Esri Download Estimate ---

class EsriEstimateRequest(BaseModel):
    output_formats: Optional[list[str]] = None
    chunk_size: Optional[int] = None


class EsriLayerEstimate(BaseModel):
    layer_id: int
    layer_name: str
    feature_count: Optional[int]
    chunk_size: int
    estimated_chunks: int
    geometry_type: str
    spatial_reference: str
    output_formats: list[str]
    confidence: str
    notes: list[str]


class EsriEstimateResponse(BaseModel):
    service_url: str
    total_layers: int
    total_features: Optional[int]
    total_chunks: int
    low_confidence_count: int
    layers: list[EsriLayerEstimate]


# --- Esri Download Request ---

class EsriDownloadRequest(BaseModel):
    output_formats: Optional[list[str]] = None


# --- Survey Projects ---

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    geometry_type: str  # point | line | polygon
    form_schema: list = []


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class FormSchemaUpdate(BaseModel):
    form_schema: list


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    geometry_type: str
    form_schema: list
    layer_id: Optional[str] = None
    is_published: bool
    feature_count: int
    created_at: datetime
    updated_at: datetime


class FeatureCreate(BaseModel):
    geometry: dict
    attributes: dict = {}
    created_by: Optional[str] = None


class FeatureUpdate(BaseModel):
    geometry: Optional[dict] = None
    attributes: Optional[dict] = None


class FeatureResponse(BaseModel):
    id: str
    project_id: str
    geometry: dict
    attributes: dict
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AttachmentResponse(BaseModel):
    id: str
    project_id: str
    filename: str
    url: str
    content_type: Optional[str] = None
    size_bytes: int


class PublishResponse(BaseModel):
    project_id: str
    layer_id: str
    geojson_url: str
