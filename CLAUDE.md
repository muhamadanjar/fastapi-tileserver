# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

A tile service that converts geospatial sources (vector `.shp`/GeoJSON/GPKG/KML and raster GeoTIFF/IMG) into Web Mercator PNG image tiles. Supports both small direct uploads and large resumable chunked uploads. Background tiling runs via Celery worker (RabbitMQ broker).

## Prerequisites

- Python 3.11+ (project uses 3.11.15)
- Docker (for RabbitMQ)

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your configuration:
#   DB_TYPE, DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME (PostgreSQL/MySQL)
#   RABBITMQ_URL, REDIS_URL, CHUNK_UPLOAD_THRESHOLD

# Run FastAPI dev server (auto-applies migrations on startup)
uvicorn app.main:app --reload
# API docs: http://localhost:8000/docs (Swagger UI)
# Alternative docs: http://localhost:8000/redoc (ReDoc)
# Health check: http://localhost:8000/

# Run Celery tiling worker (separate terminal, requires RabbitMQ running)
celery -A app.workers.celery_app worker --loglevel=info

# Run RabbitMQ (Docker)
docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management
# Management console: http://localhost:15672 (guest/guest)

# Create database migration
./scripts/make_migration.sh "description of changes"

# Manually run migrations (auto-run on app startup)
alembic upgrade head
```

No test suite or linter is configured.

## Architecture

Clean Architecture layered structure:

- **`app/api/v1/endpoints/`** — HTTP layer.
  - `tiles.py` — `POST /upload` direct upload (file < `CHUNK_UPLOAD_THRESHOLD`).
  - `upload.py` — Chunked upload: `POST /uploads/init`, `PATCH /uploads/{upload_id}`, `GET /uploads/{upload_id}/status`. Tiling trigger: `POST /uploads/{upload_id}/tile`. GeoServer publish: `POST /uploads/{upload_id}/geoserver`.
- **`app/usecases/`** — Orchestration.
  - `ProcessUploadUseCase` — saves file, persists `UploadSession` with status `uploaded` (no auto-tiling).
  - `InitChunkedUploadUseCase` — creates upload session + chunk directory.
  - `ReceiveChunkUseCase` — stores chunk part, assembles on last chunk, sets status `uploaded` (no auto-tiling).
- **`app/infrastructure/`** — Side effects:
  - `services/file_service.py` — `FileService`: save uploads, validate formats, extract ZIPs, `prepare_source_path()` reused by both flows.
  - `services/tiling_service.py` — `TilingService.process_tiling()`, `VectorTiler`, `RasterTiler`.
  - `db/connection.py` — Database engines (sync + async) for `UploadSession` + `Layer` tracking. Runs Alembic migrations on startup.
  - `db/repository.py` — `UploadSessionRepository` (async, for FastAPI) and `SyncUploadSessionRepository` (sync, for worker).
  - `storage/chunk_storage.py` — `ChunkStorage`: write `.part` files, assemble into final file.
  - `config/database.py` — `DatabaseSettings` parses DB config from `.env` (supports PostgreSQL, MySQL, SQLite).
- **`app/domain/models.py`** — `UploadSession` SQLModel table; `JobStatus` enum.
- **`app/domain/schemas.py`** — Pydantic request/response models.
- **`app/core/config.py`** — `Settings` reads `.env`; exposes `UPLOAD_DIR`, `TILES_DIR`, `CHUNKS_DIR`, `RABBITMQ_URL`, `CHUNK_UPLOAD_THRESHOLD`.
- **`app/workers/celery_app.py`** — Celery app instance, configured with RabbitMQ broker + rpc:// result backend.
- **`app/workers/tasks.py`** — `@celery_app.task process_tiling_task()` — calls `TilingService.process_tiling()`, updates `UploadSession` status.

### Upload flows

Upload completes with status `uploaded` (file ready, not yet processed). User then chooses:
1. Tile via tileserver: `POST /uploads/{upload_id}/tile`
2. Publish to GeoServer: `POST /uploads/{upload_id}/geoserver`

**Small file (< `CHUNK_UPLOAD_THRESHOLD`, default 10 MB):**
```
POST /api/v1/upload   (multipart/form-data)
→ file saved → UploadSession created with status=uploaded → 200 TilingJobResponse
```

**Large file (chunked, pause/resume):**
```
POST /api/v1/uploads/init              { filename, total_size }
→ UploadSession created, returns upload_id + chunk_size

PATCH /api/v1/uploads/{upload_id}      Content-Range: bytes 0-10485759/52428800
→ chunk stored as data/chunks/{upload_id}/{index}.part
→ on last chunk: file assembled → FileService.prepare_source_path() → status=uploaded

GET /api/v1/uploads/{upload_id}/status
→ { status: uploaded|processing|done|failed, received_bytes, total_size }
```

**Trigger tiling:**
```
POST /api/v1/uploads/{upload_id}/tile
→ status=processing → Celery task queued → status=done → tile_url_template populated
```

**Publish to GeoServer (SHP only):**
```
POST /api/v1/uploads/{upload_id}/geoserver
→ status=processing → GeoServer REST publish → Layer created with wms_url → status=done
```

### Tiling flow

1. User calls `POST /uploads/{upload_id}/tile` (manual trigger, not automatic).
2. Endpoint sets `UploadSession.status = processing`, queues Celery task.
3. Celery worker receives `process_tiling_task` from RabbitMQ broker.
4. Calls `TilingService.process_tiling(file_type, source_path, layer_id)`.
5. Updates status to `done` or `failed` (with error_message on failure).
6. Tiles served statically at `/tiles/<layer_id>/{z}/{x}/{y}.png`.

### GeoServer publish flow (SHP only)

1. User calls `POST /uploads/{upload_id}/geoserver` with SHP file (manual trigger).
2. Endpoint sets `UploadSession.status = processing`.
3. `GeoServerService.publish_shp()` uploads to GeoServer via REST API.
4. Creates workspace + datastore + featureType, returns WMS/WFS URLs.
5. Layer record created with `layer_type=wms`, `tile_url_template=WMS_URL`, `file_metadata.geoserver` populated.
6. Updates status to `done` or `failed`.

### Data directory layout

```
data/
  uploads/     # final assembled source files
  tiles/       # output tile PNGs: {layer_id}/{z}/{x}/{y}.png
  chunks/      # temp chunk parts: {upload_id}/{index}.part  (cleaned after assembly)
```

Database tables stored in PostgreSQL (or configured DB backend), not as files.

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

## Database Migrations (Alembic)

Schema versioning using Alembic with Django-style sequential migration naming (`0001_`, `0002_`, etc).

### Setup

Migrations auto-run on app startup via `app/db/connection.py` which calls `alembic upgrade head`.

### Create new migration

```bash
# Simple way: auto-generates and renames
./scripts/make_migration.sh "add new column to layers"
# Creates: alembic/versions/0002_add_new_column_to_layers.py

# Manual way (if script fails):
alembic revision -m "add new column to layers"
# Then manually rename file to: 0002_add_new_column_to_layers.py
# And update revision: str = '0002_...' in the file
```

### Apply migrations

```bash
# Auto-applied on server startup
uvicorn app.main:app --reload

# Manual apply:
alembic upgrade head

# Check status:
alembic current    # shows applied version
alembic history    # shows all versions

# Rollback last:
alembic downgrade -1

# Rollback to specific version:
alembic downgrade 0001_initial_schema
```

### Write migrations

**Auto-detect changes** (experimental):
```bash
# Requires env.py configured for autogenerate
alembic revision --autogenerate -m "message"
# Then review generated file before running
```

**Manual migration** (recommended):

```python
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.add_column('layers', sa.Column('new_field', sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column('layers', 'new_field')
```

Common operations:
- `op.create_table(name, sa.Column(...), ...)` — create table
- `op.drop_table(name)` — drop table
- `op.add_column(table, sa.Column(...))` — add column
- `op.drop_column(table, col_name)` — drop column
- `op.alter_column(table, col_name, new_column_name=...)` — rename/modify column
- `op.create_index(...)`, `op.drop_index(...)` — index management
- `op.add_constraint(...)`, `op.drop_constraint(...)` — constraints

### Current schema

**Tables:**
- `upload_sessions` — upload metadata + chunk tracking (id, filename, layer_id, status, chunk_map, expires_at, etc)
- `layers` — layer configuration (id, filename, layer_type, tile_url_template, bbox, visibility, etc)

**FK:** `layers.upload_session_id` → `upload_sessions.id` (nullable)

See `app/domain/models.py` for full schema.

### Database support

- **PostgreSQL** (production, current)
- **MySQL** (supported via config)
- **SQLite** (dev-only, no concurrent writes)

Set via `.env`: `DB_TYPE=postgresql|mysql|sqlite`

## Verification & Troubleshooting

**Verify services are running:**
```bash
# FastAPI dev server
curl http://localhost:8000/

# RabbitMQ connectivity
docker ps | grep rabbitmq  # or check http://localhost:15672

# Celery worker logs should show "Connected to amqp://..."
# If connection fails, check RABBITMQ_URL in .env
```

**Common issues:**
- `ConnectionError` connecting to RabbitMQ: Ensure RabbitMQ Docker container is running (`docker start rabbitmq`)
- Celery task not running: Check that Celery worker is running in a separate terminal
- Database locked errors: Only run one worker instance at a time; SQLite doesn't support concurrent writes well
- File permissions: Ensure `data/` directory is writable (`chmod -R 755 data/`)

**Database migration issues:**
- `ALEMBIC_SQLALCHEMY_URL` not set: Ensure `.env` has DB_* vars; `app/db/connection.py` reads them
- Migration fails on app startup: Run `alembic current` to check applied versions, `alembic history` for all versions
- Foreign key constraint error: Ensure tables are created in correct order (upload_sessions before layers)
- "target_metadata has no tables": Confirm `app/domain/models.py` imports are correct in `alembic/env.py`

## Rules

- **Commits are FORBIDDEN** — Claude must NOT run `git commit` under any circumstances
- **Git read-only** — Only these operations are allowed: `git log`, `git status`, `git diff`, `git show`
- **FORBIDDEN: `git commit`, `git push`, `git merge`, `git rebase`, `git reset`** — all git write operations are prohibited
