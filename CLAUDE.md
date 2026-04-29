# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

A tile service that converts geospatial sources (vector `.shp`/GeoJSON/GPKG/KML and raster GeoTIFF/IMG) into Web Mercator PNG image tiles. Supports both small direct uploads and large resumable chunked uploads. Background tiling runs via RabbitMQ.

## Prerequisites

- Python 3.11+ (project uses 3.11.15)
- Docker (for RabbitMQ)

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and configure environment (.env.example has RABBITMQ_URL, CHUNK_UPLOAD_THRESHOLD, DB_* vars)
cp .env.example .env
# Edit .env with your configuration if needed

# Run FastAPI dev server
uvicorn app.main:app --reload
# API docs: http://localhost:8000/docs (Swagger UI)
# Alternative docs: http://localhost:8000/redoc (ReDoc)
# Health check: http://localhost:8000/

# Run tiling worker (separate terminal, requires RabbitMQ running)
python -m app.workers.tiling_worker

# Run RabbitMQ (Docker)
docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management
# Management console: http://localhost:15672 (guest/guest)
```

No test suite or linter is configured.

## Architecture

Clean Architecture layered structure:

- **`app/api/v1/endpoints/`** — HTTP layer.
  - `tiles.py` — `POST /upload-and-tile` direct upload (file < `CHUNK_UPLOAD_THRESHOLD`).
  - `upload.py` — Chunked upload: `POST /uploads/init`, `PATCH /uploads/{upload_id}`, `GET /uploads/{upload_id}/status`.
- **`app/usecases/`** — Orchestration.
  - `ProcessUploadUseCase` — saves file, persists `UploadSession`, publishes RabbitMQ job.
  - `InitChunkedUploadUseCase` — creates upload session + chunk directory.
  - `ReceiveChunkUseCase` — stores chunk part, assembles on last chunk, publishes RabbitMQ job.
- **`app/infrastructure/`** — Side effects:
  - `services/file_service.py` — `FileService`: save uploads, validate formats, extract ZIPs, `prepare_source_path()` reused by both flows.
  - `services/tiling_service.py` — `TilingService.process_tiling()`, `VectorTiler`, `RasterTiler`.
  - `broker/publisher.py` — `RabbitMQPublisher` (aio-pika): connect at startup, publish JSON messages to `tiling_jobs` queue.
  - `db/connection.py` — SQLite engines (sync + async) for `UploadSession` tracking.
  - `db/repository.py` — `UploadSessionRepository` (async, for FastAPI) and `SyncUploadSessionRepository` (sync, for worker).
  - `storage/chunk_storage.py` — `ChunkStorage`: write `.part` files, assemble into final file.
- **`app/domain/models.py`** — `UploadSession` SQLModel table; `JobStatus` enum.
- **`app/domain/schemas.py`** — Pydantic request/response models.
- **`app/core/config.py`** — `Settings` reads `.env`; exposes `UPLOAD_DIR`, `TILES_DIR`, `CHUNKS_DIR`, `RABBITMQ_URL`, `CHUNK_UPLOAD_THRESHOLD`.
- **`app/workers/tiling_worker.py`** — Standalone pika consumer; calls `TilingService.process_tiling()`, updates `UploadSession` status.

### Upload flows

**Small file (< `CHUNK_UPLOAD_THRESHOLD`, default 10 MB):**
```
POST /api/v1/upload-and-tile   (multipart/form-data)
→ file saved → UploadSession created → RabbitMQ job published → 200 TilingJobResponse
```

**Large file (chunked, pause/resume):**
```
POST /api/v1/uploads/init              { filename, total_size }
→ UploadSession created, returns upload_id + chunk_size

PATCH /api/v1/uploads/{upload_id}      Content-Range: bytes 0-10485759/52428800
→ chunk stored as data/chunks/{upload_id}/{index}.part
→ on last chunk: file assembled → FileService.prepare_source_path() → RabbitMQ job published

GET /api/v1/uploads/{upload_id}/status
→ { status: pending|processing|done|failed, received_bytes, total_size }
```

### Tiling flow

1. Worker receives JSON from `tiling_jobs` queue.
2. Updates `UploadSession.status = processing`.
3. Calls `TilingService.process_tiling(file_type, source_path, layer_id)`.
4. Updates status to `done` or `failed`.
5. Tiles served statically at `/tiles/<layer_id>/{z}/{x}/{y}.png`.

### Data directory layout

```
data/
  uploads/     # final assembled source files
  tiles/       # output tile PNGs: {layer_id}/{z}/{x}/{y}.png
  chunks/      # temp chunk parts: {upload_id}/{index}.part  (cleaned after assembly)
  sessions.db  # SQLite: UploadSession table
```

### Supported input formats

| Format | Type |
|---|---|
| `.shp`, `.geojson`, `.json`, `.gpkg`, `.kml` | vector |
| `.zip` (containing `.shp`) | vector |
| `.tif`, `.tiff`, `.img`, `.png`, `.jpg` | raster |

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `RABBITMQ_URL` | `amqp://guest:guest@localhost:5672/` | RabbitMQ connection |
| `CHUNK_UPLOAD_THRESHOLD` | `10485760` | Byte limit for direct upload (10 MB) |
| `BACKEND_CORS_ORIGINS` | (empty) | Comma-separated CORS origins (e.g., `http://localhost:3000`) |
| `DB_USER/PASS/HOST/PORT/NAME` | postgres defaults | PostGIS (future use) |

## Verification & Troubleshooting

**Verify services are running:**
```bash
# FastAPI dev server
curl http://localhost:8000/

# RabbitMQ connectivity
docker ps | grep rabbitmq  # or check http://localhost:15672

# Worker logs should show connection to RabbitMQ
# If no "Connected to RabbitMQ" message, check RABBITMQ_URL in .env
```

**Common issues:**
- `ConnectionError` connecting to RabbitMQ: Ensure RabbitMQ Docker container is running (`docker start rabbitmq`)
- Database locked errors: Only run one worker instance at a time; SQLite doesn't support concurrent writes well
- File permissions: Ensure `data/` directory is writable (`chmod -R 755 data/`)
