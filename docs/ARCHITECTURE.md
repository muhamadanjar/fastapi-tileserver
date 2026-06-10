# Architecture

Layered Clean Architecture: HTTP → Use Cases → Services → Domain

## Directory Structure

```
tileserver_api/
├── app/
│   ├── api/
│   │   └── v1/
│   │       └── endpoints/
│   │           ├── tiles.py        # Direct upload (small files)
│   │           └── upload.py       # Chunked upload + tiling trigger
│   ├── usecases/
│   │   ├── init_chunked_upload.py  # Create upload session + chunk directory
│   │   ├── receive_chunk.py        # Store chunk, assemble on last
│   │   └── process_upload.py       # Save file, create UploadSession
│   ├── infrastructure/
│   │   ├── services/
│   │   │   ├── file_service.py       # File I/O, format validation, ZIP extraction
│   │   │   ├── tiling_service.py     # VectorTiler, RasterTiler, tile generation
│   │   │   ├── geoserver_service.py  # GeoServer REST API integration
│   │   │   ├── bbox_extractor.py     # Extract bbox + CRS from files
│   │   │   └── csw_sync.py           # Catalog sync (if needed)
│   │   ├── db/
│   │   │   ├── connection.py         # SQLAlchemy engines + Alembic auto-migrate
│   │   │   └── repository.py         # UploadSessionRepository, LayerRepository
│   │   └── storage/
│   │       └── chunk_storage.py      # ChunkStorage: write .part, assemble
│   ├── domain/
│   │   ├── models.py       # UploadSession, Layer (SQLModel tables)
│   │   └── schemas.py      # Pydantic request/response models
│   ├── workers/
│   │   ├── celery_app.py      # Celery app instance + config
│   │   └── tasks.py           # @celery_app.task process_tiling_task
│   ├── core/
│   │   ├── config.py      # Settings from .env
│   │   ├── response.py    # Response envelope (status, data, metas, message)
│   │   ├── exceptions.py  # Custom exceptions
│   │   └── utils.py       # Utility functions
│   └── main.py            # FastAPI app + middleware + startup events
├── alembic/
│   ├── versions/          # Migration files (0001_..., 0002_...)
│   ├── env.py             # Alembic configuration
│   └── script.py.mako     # Migration template
├── scripts/
│   └── make_migration.sh  # Helper to create + rename migrations
├── data/
│   ├── uploads/           # Final assembled source files
│   ├── tiles/             # Output tile PNGs: {layer_id}/{z}/{x}/{y}.png
│   └── chunks/            # Temp chunk parts: {upload_id}/{index}.part
├── .env                   # Environment variables (git-ignored)
├── .env.example           # Example config
├── requirements.txt       # Python dependencies
└── CLAUDE.md              # Development guide (this repo)
```

## Components

### HTTP Layer (`api/v1/endpoints/`)

**tiles.py — Direct Upload**
- `POST /upload` — multipart file upload (< 10 MB threshold)
- Dependency injection: `ProcessUploadUseCase` via Depends
- Response: `TilingJobResponse` with upload_id, layer_id, status

**upload.py — Chunked Upload & Tiling**
- `POST /uploads/init` — initialize chunked session, returns chunk_size + total_chunks
- `PATCH /uploads/{upload_id}` — receive chunk via Content-Range header
- `GET /uploads/{upload_id}/status` — poll progress
- `POST /uploads/{upload_id}/tile` — queue tiling task
- `POST /uploads/{upload_id}/geoserver` — publish to GeoServer

All use FastAPI `Depends()` for injection of repository + services.

---

### Use Cases (`usecases/`)

Orchestrate domain logic + infrastructure. No direct HTTP awareness.

**InitChunkedUploadUseCase**
```python
async def execute(filename, total_size, output_format, max_zoom) -> UploadSession:
    # 1. Validate file format (extension check)
    # 2. Generate upload_id + layer_id (slugify filename)
    # 3. Calculate chunk_size, total_chunks
    # 4. Create UploadSession in DB (status=pending)
    # 5. Create chunk directory data/chunks/{upload_id}/
    # 6. Return session
```

**ReceiveChunkUseCase**
```python
async def execute(upload_id, chunk_index, chunk_data) -> UploadSession:
    # 1. Fetch session from DB
    # 2. Validate upload not expired/complete
    # 3. Write chunk to data/chunks/{upload_id}/{chunk_index}.part
    # 4. Record in chunk_map
    # 5. If last chunk:
    #    a. Assemble parts via ChunkStorage.assemble()
    #    b. Save to data/uploads/{filename}
    #    c. Set status=uploaded, final_path
    # 6. Return updated session
```

**ProcessUploadUseCase**
```python
async def execute(file, output_format, max_zoom) -> TilingJobResponse:
    # 1. FileService validates + saves file
    # 2. Extract file type, bbox
    # 3. Create UploadSession (status=uploaded)
    # 4. Return TilingJobResponse
```

**QueryLayerFeaturesUseCase** (`getinfo_layer.py`)
```python
async def execute(layer_id, lon, lat) -> FeatureQueryResponse:
    # 1. Fetch layer, dispatch per type:
    #    - vector/raster lokal → geopandas/rasterio pada source file
    #    - external wms/wmts/wfs/esri → proxy GetFeatureInfo/GetFeature/identify
    # 2. Apply field configs (file_metadata.fields) — visible only
```

**GetLayerFieldsUseCase** (`get_layer_fields.py`)
```python
async def execute(layer_id) -> LayerFieldsResponse:
    # 1. Fetch layer; raise LayerNotFoundError jika tidak ada
    # 2. Resolve source path dari upload session
    # 3. Per tipe:
    #    - vector lokal  → kolom file (geopandas)
    #    - raster lokal  → band_1..band_N (rasterio)
    #    - external WMS  → source lokal kalau ada (publish flow),
    #                      else remote WFS DescribeFeatureType
    #    - external lain → raise LayerFieldsUnavailableError
```

---

### Services (`infrastructure/services/`)

Pure business logic + external I/O.

**FileService**
- `save_upload(file) → str` — save UploadFile to data/uploads/{filename}
- `validate_format(filename) → str` — check extension, return file_type
- `prepare_source_path(path) → str` — handle ZIP extraction, return inner file
- `extract_bbox(path) → tuple` — geometry bounds (west, south, east, north)

**TilingService**
```python
def process_tiling(file_type, source_path, layer_id, output_format, max_zoom):
    # 1. Load source file (geopandas for vector, rasterio for raster)
    # 2. Reproject to EPSG:3857 (Web Mercator)
    # 3. Calculate optimal max_zoom if not provided
    # 4. Generate tiles via VectorTiler or RasterTiler
    # 5. Save PNG files to data/tiles/{layer_id}/{z}/{x}/{y}.png
    # 6. Return bbox (extracted during tiling)
```

**VectorTiler**
- Loads GeoJSON/SHP/GPKG via geopandas
- Reprojects to EPSG:3857
- Uses mercantile to calculate tile grid
- For each tile: query geometries via spatial index, encode as MVT or rasterize to PNG
- Outputs: PNG tiles at data/tiles/{layer_id}/{z}/{x}/{y}.png

**RasterTiler**
- Loads GeoTIFF/IMG via rasterio
- Warps to EPSG:3857 if needed
- Tiles via mercantile grid
- For each tile: clip raster, resample to tile size, save PNG
- Outputs: PNG tiles at data/tiles/{layer_id}/{z}/{x}/{y}.png

**GeoServerService**
- REST API client for GeoServer
- `publish_shp(file_path, store_name)` — uploads SHP to GeoServer
- Creates workspace (if needed), datastore, featureType
- Returns WMS/WFS URLs
- Used by `POST /uploads/{id}/geoserver` endpoint

**BboxExtractor**
- `extract_bbox_from_file(path) → (west, south, east, north)`
- Reads geometry bounds from any supported format
- Returns None if extraction fails

**ChunkStorage**
- `write_part(upload_id, chunk_index, data)` — save .part file
- `assemble(upload_id, total_chunks, output_path)` — merge parts into final file

---

### Database (`infrastructure/db/`)

**connection.py**
```python
# Create engines
sync_engine = create_engine(db_url, echo=False)
async_engine = create_async_engine(async_db_url)

# Auto-run migrations on app startup
alembic upgrade head
```

Supports PostgreSQL, MySQL, SQLite via config.

**repository.py**
```python
class UploadSessionRepository:
    async def create(session_data) -> UploadSession
    async def get_by_id(upload_id) -> UploadSession | None
    async def set_status(upload_id, status, error_message) -> None
    async def list(page, limit) -> list[UploadSession]
    async def update(upload_id, **kwargs) -> None
```

Uses async SQLAlchemy for FastAPI compatibility.

**SyncUploadSessionRepository**
- Sync version for Celery worker (no async)
- Same methods, blocking I/O

---

### Domain (`domain/`)

**models.py**
```python
class UploadSession(SQLModel):
    id: str (PK)
    filename: str
    file_type: str
    layer_id: str
    total_size: int
    received_bytes: int
    status: str  # pending, uploading, uploaded, processing, done, failed, expired
    error_message: Optional[str]
    final_path: Optional[str]  # path to assembled file
    output_format: str  # raster, mvt
    max_zoom: Optional[int]
    chunk_map: Dict[str, int]  # {chunk_index: byte_count}
    total_chunks: int
    uploaded_chunks: int
    chunk_size: int
    expires_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

class Layer(SQLModel):
    id: str (PK)
    upload_session_id: Optional[str] (FK)
    code: Optional[str]
    layer_type: str  # tile, mvt, wms, etc
    filename: str
    file_type: str
    tile_url_template: str  # /tiles/{layer_id}/{z}/{x}/{y}.png
    is_active: bool
    is_visible: bool
    opacity: float
    sorting: int
    file_metadata: Optional[Dict]  # custom metadata (geoserver, etc)
    abstract: Optional[str]
    topic_category: Optional[str]
    language: str
    bbox_west, bbox_south, bbox_east, bbox_north: Optional[float]
    created_at: datetime
    updated_at: datetime

class JobStatus(str, Enum):
    pending, uploading, uploaded, processing, done, failed, expired
```

**schemas.py** — Pydantic request/response models
```python
class UploadInitRequest
class UploadInitResponse
class JobStatusResponse
class ChunkUploadResponse
class TilingJobResponse
```

---

### Workers (`workers/`)

**celery_app.py**
```python
celery_app = Celery('tileserver')
celery_app.conf.broker_url = RABBITMQ_URL
celery_app.conf.result_backend = 'rpc://'
```

RabbitMQ as broker, no persistent result backend (fire-and-forget).

**tasks.py**
```python
@celery_app.task(bind=True)
def process_tiling_task(self, upload_id, layer_id, file_type, source_path, 
                       output_format, max_zoom):
    # 1. Fetch session from DB (sync)
    # 2. Set status=processing
    # 3. Call TilingService.process_tiling()
    # 4. Extract bbox
    # 5. Create/update Layer record
    # 6. Set status=done
    # 7. On error: status=failed, error_message
```

Runs in separate Celery worker process, connected to RabbitMQ.

---

### Core (`core/`)

**config.py**
```python
class Settings(BaseSettings):
    RABBITMQ_URL: str
    CHUNK_UPLOAD_THRESHOLD: int
    UPLOAD_DIR: str
    TILES_DIR: str
    CHUNKS_DIR: str
    DB_TYPE, DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_PORT: str
    GEOSERVER_URL, GEOSERVER_USER, GEOSERVER_PASSWORD, GEOSERVER_WORKSPACE: str
    BACKEND_CORS_ORIGINS: str
```

Reads from `.env` via Pydantic.

**response.py**
```python
class ResponseData:
    status: str  # success, error
    data: Any
    metas: dict  # page, limit, total
    message: str
```

Standard response envelope for all endpoints.

**exceptions.py**
```python
class ChunkUploadError(Exception)
class SessionNotFoundError(Exception)
class SessionExpiredError(Exception)
class SessionAlreadyCompleteError(Exception)
class UnsupportedFileFormatException(Exception)
class TilingProcessError(Exception)
```

---

## Data Flow

### Direct Upload (Small File)

```
POST /upload (multipart)
    ↓
ProcessUploadUseCase.execute()
    ├─ FileService.save_upload() → /data/uploads/{filename}
    ├─ FileService.extract_bbox()
    ├─ Create UploadSession(status=uploaded)
    └─ Return TilingJobResponse
    ↓
User gets upload_id, layer_id, status=uploaded
```

Manual trigger needed: `POST /uploads/{id}/tile`

### Chunked Upload (Large File)

```
POST /uploads/init { filename, total_size }
    ↓
InitChunkedUploadUseCase.execute()
    ├─ Create UploadSession(status=pending)
    ├─ mkdir /data/chunks/{upload_id}/
    └─ Return upload_id, chunk_size
    ↓
PATCH /uploads/{upload_id} × N (multiple chunks)
    ↓
ReceiveChunkUseCase.execute() [per chunk]
    ├─ Write /data/chunks/{upload_id}/{index}.part
    ├─ Update chunk_map, received_bytes
    ├─ If last chunk: ChunkStorage.assemble()
    │   ├─ Merge .part files → /data/uploads/{filename}
    │   └─ Set status=uploaded, final_path
    └─ Return updated session
    ↓
User gets status=uploaded
    ↓
Manual trigger: POST /uploads/{upload_id}/tile
    ↓
Endpoint queues Celery task
```

### Tiling (Background)

```
POST /uploads/{upload_id}/tile
    ↓
Endpoint:
    ├─ Set status=processing
    └─ Queue Celery task
    ↓
Celery Worker (separate process):
    ├─ process_tiling_task() receives message from RabbitMQ
    ├─ TilingService.process_tiling():
    │   ├─ Load source file (geopandas or rasterio)
    │   ├─ Reproject to EPSG:3857
    │   ├─ Calculate max_zoom if needed
    │   ├─ VectorTiler or RasterTiler generates tiles
    │   └─ Save /data/tiles/{layer_id}/{z}/{x}/{y}.png
    ├─ Extract bbox from processed file
    ├─ Create Layer record
    ├─ Set status=done
    └─ On error: status=failed, error_message
    ↓
User polls GET /uploads/{upload_id}/status until done
    ↓
GET /tiles/{layer_id}/{z}/{x}/{y}.png ← tiles ready
```

---

## Data Storage

**Uploaded Files:** `/data/uploads/{filename}`
- Source files (GeoJSON, SHP, GeoTIFF, etc)
- Persisted after tiling completes

**Tiles:** `/data/tiles/{layer_id}/{z}/{x}/{y}.png`
- Output PNG tiles, organized by zoom + tile grid
- Served statically

**Chunk Temp:** `/data/chunks/{upload_id}/{index}.part`
- Deleted after assembly

**Database:** PostgreSQL (or MySQL/SQLite)
- `upload_sessions` — status, metadata, chunk tracking
- `layers` — layer config, URLs, styling

---

## Message Queue (Celery + RabbitMQ)

**Broker:** RabbitMQ (AMQP protocol)
- Connection: `amqp://guest:guest@localhost:5672/`
- Default vhost: `/`

**Task:** `process_tiling_task`
- Queued by endpoint: `task.delay(upload_id=..., ...)`
- Processed by worker: `celery -A app.workers.celery_app worker`

**Result Backend:** None (rpc://)
- Fire-and-forget; worker updates DB directly
- No need for Redis/Memcached

---

## Deployment

- **FastAPI server** — `uvicorn app.main:app` (HTTP on port 8080)
- **Celery worker** — `celery -A app.workers.celery_app worker` (background tasks)
- **RabbitMQ** — Docker container (broker)
- **Database** — PostgreSQL (or MySQL/SQLite)
- **File storage** — Local filesystem or S3 (future)
