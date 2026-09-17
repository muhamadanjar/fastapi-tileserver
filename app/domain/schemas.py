import math

from pydantic import BaseModel, Field, field_validator
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
    # `batch` only stages an archive for ZIP inspection; its final output is
    # selected later by the batch configure endpoint.
    workflow: Literal["layer", "batch"] = "layer"
    output_format: Optional[Literal["raster", "mvt"]] = None
    max_zoom: Optional[int] = None


class ArtifactTilingResponse(BaseModel):
    upload_id: str
    layer_id: str
    artifact_id: str
    status: str
    task_id: Optional[str] = None


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


class ShapefileImportedTable(BaseModel):
    schema_name: str = Field(default="geodata", serialization_alias="schema")
    table: str
    geometry_family: Optional[str] = None
    row_count: int
    bbox: Optional[list[float]] = None


class ShapefileImportStatus(BaseModel):
    status: str
    task_id: Optional[str] = None
    schema_name: str = Field(default="geodata", serialization_alias="schema")
    table: Optional[str] = None
    processed_rows: int = 0
    total_rows: int = 0
    progress_percent: float = 0.0
    row_count: Optional[int] = None
    tables: list[ShapefileImportedTable] = Field(default_factory=list)
    error: Optional[str] = None
    imported_at: Optional[datetime] = None


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
    import_process: ShapefileImportStatus = Field(serialization_alias="import")


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
    style_verified: Optional[bool] = None
    default_style_name: Optional[str] = None


class KodefikasiRequest(BaseModel):
    code_field: Optional[str] = Field(default=None, max_length=100, description="Primary field that holds kode, e.g. KODE")
    catalog_code: str = Field(min_length=1, max_length=30, description="Planning catalog code, e.g. RDTR_LAHAT_2024")
    plan_component: str = Field(default="PR", pattern="^(PR|SR)$")
    enrich_fields: Optional[list[str]] = Field(default=None, description="Additional fields to enrich, e.g. [KODKWS, JNSRPR]")


class PatchLayerRequest(BaseModel):
    file_metadata: Optional[dict] = None
    filename: Optional[str] = None
    layer_type: Optional[str] = None
    tile_url_template: Optional[str] = None
    source_url: Optional[str] = None
    refresh_bbox: bool = False
    abstract: Optional[str] = None
    topic_category: Optional[str] = None
    language: Optional[str] = None


def _validate_wgs84_bbox(bbox: Optional[list[float]]) -> Optional[list[float]]:
    if bbox is None:
        return None
    if len(bbox) != 4:
        raise ValueError("bbox must contain exactly four values: west, south, east, north")

    west, south, east, north = bbox
    if not all(math.isfinite(value) for value in bbox):
        raise ValueError("bbox values must be finite numbers")
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox must be a non-degenerate WGS84 extent")
    return bbox


class SyncBBoxRequest(BaseModel):
    bbox: list[float]

    _validate_bbox = field_validator("bbox")(_validate_wgs84_bbox)


class LayerStyleRequest(BaseModel):
    mode: Literal["simple", "sld"]
    style: Optional[dict] = None      # required when mode=simple; geometry-keyed JSON
    sld_body: Optional[str] = None    # required when mode=sld; raw SLD XML


class LayerStyleResponse(BaseModel):
    layer_id: str
    style_name: str
    style: Optional[dict] = None      # stored editor state incl. mode, None if never styled


class LayerLegendResponse(BaseModel):
    layer_id: str
    layer_type: str
    available: bool
    legend_url: Optional[str] = None
    format: Optional[str] = None
    detail: Optional[str] = None


class LayerFieldsResponse(BaseModel):
    layer_id: str
    fields: list[str]


class ExternalLayerRequest(BaseModel):
    layer_type: str
    filename: str
    source_url: str
    params: Optional[dict] = None
    file_metadata: Optional[dict] = None
    bbox: Optional[list[float]] = None

    _validate_bbox = field_validator("bbox")(_validate_wgs84_bbox)


class FeatureQueryResponse(BaseModel):
    type: str
    count: int
    features: Optional[list[dict]] = None
    values: Optional[dict[str, float]] = None
    # "client" when the layer is rendered client-side (mvt/geojson/kml/esri_*) and
    # the frontend should query the already-loaded features instead of a backend query.
    query_hint: Optional[str] = None


class FieldUniqueValuesResponse(BaseModel):
    layer_id: str
    field_name: str
    values: list[str]


class BboxFeaturesResponse(BaseModel):
    layer_id: str
    count: int
    exceeded: bool
    features: list[dict[str, Any]]
    queryable: bool = True
    reason: Optional[str] = None


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


# --- Overlay Analysis ---

class AnalysisRequest(BaseModel):
    operation: str  # OverlayOperation value
    input_layer_a_id: str
    input_layer_b_id: Optional[str] = None
    output_name: Optional[str] = None
    selected_attributes: Optional[Dict[str, list[str]]] = None
    buffer_distance: Optional[float] = None
    buffer_unit: Optional[str] = "meters"  # meters|kilometers|feet|miles
    dissolve_group_by: Optional[str] = None
    simplify_tolerance: Optional[float] = None  # simplify: tolerance in geometry units
    join_predicate: Optional[str] = "intersects"  # spatial_join: intersects|within|contains|touches|crosses|overlaps
    async_run: bool = False  # execute via Celery worker
    calculate_area: bool = Field(
        default=False,
        description="Polygon intersection only: include per-pair area and percentages",
    )
    source_id_field_a: Optional[str] = Field(default=None, min_length=1)
    source_id_field_b: Optional[str] = Field(default=None, min_length=1)


class AnalysisResponse(BaseModel):
    result_layer_id: str
    operation: str
    feature_count: int
    skipped_null_geometry: int = 0
    warning: Optional[str] = None
    bbox: Optional[list[float]] = None
    geojson_url: str
    async_task_id: Optional[str] = None


class AnalysisStatusResponse(BaseModel):
    result_id: str
    result_layer_id: str
    status: str  # pending|processing|done|failed
    operation: str
    feature_count: int = 0
    warning: Optional[str] = None
    error_message: Optional[str] = None
    bbox: Optional[list[float]] = None
    geojson_url: Optional[str] = None


class OperationInfo(BaseModel):
    name: str
    display_name: str
    description: str
    requires_second_layer: bool
    compatible_geometry: Dict[str, list[str]]  # input_a geometry types -> compatible input_b types
    output_geometry: str
    phase: int = 1
    optional_params: list[str] = []


class LayerAnalysisSource(BaseModel):
    layer_id: str
    filename: str
    layer_type: str
    geometry_type: str
    feature_count: Optional[int] = None
    bbox: Optional[list[float]] = None
    fields: list[str] = []


class ValidateAnalysisResponse(BaseModel):
    valid: bool
    errors: list[str] = []
    warnings: list[str] = []
    layer_a_geometry: Optional[str] = None
    layer_b_geometry: Optional[str] = None
    compatible_operations: list[str] = []


class AnalysisSaveResponse(BaseModel):
    result_layer_id: str
    layer_id: str
    message: str


class AnalysisDownloadResponse(BaseModel):
    download_url: str
    format: str
    filename: str


# --- Geocoding ---

class GeocodeHit(BaseModel):
    """One Nominatim result — used both as forward geocoding target and as reverse output."""
    display_name: str
    lon: float
    lat: float
    address: Optional[dict] = None


class ReverseGeocodeResponse(BaseModel):
    feature_index: int
    longitude: float
    latitude: float
    address: Optional[GeocodeHit] = None


class ForwardMatch(BaseModel):
    feature_index: int
    distance_m: float
    properties: dict = {}
    longitude: Optional[float] = None
    latitude: Optional[float] = None


class ForwardGeocodeResponse(BaseModel):
    layer_id: Optional[str] = None
    text: str
    geocoded: Optional[GeocodeHit] = None
    count: int
    matches: list[ForwardMatch] = []


class GlobalGeocodeLayerResult(BaseModel):
    layer_id: str
    layer_name: str
    count: int
    matches: list[ForwardMatch] = []


class GlobalGeocodeResponse(BaseModel):
    text: str
    geocoded: Optional[GeocodeHit] = None
    layers: list[GlobalGeocodeLayerResult] = []
