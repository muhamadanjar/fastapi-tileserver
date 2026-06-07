# TileServer API - Overview

## Purpose

FastAPI-based geospatial tile service. Converts geographic sources (vector & raster) into Web Mercator PNG tiles. Supports small direct uploads and large resumable chunked uploads with background processing via Celery.

## Core Features

- **Direct Upload**: Small files (< 10 MB) uploaded, processed synchronously
- **Chunked Upload**: Large files split into parts, pause/resume capability, asynchronous processing
- **Format Support**:
  - Vector: `.shp`, `.geojson`, `.json`, `.gpkg`, `.kml`, `.zip` (containing `.shp`)
  - Raster: `.tif`, `.tiff`, `.img`, `.png`, `.jpg`
- **Tile Generation**: Automatic zoom level detection, customizable output format
- **GeoServer Integration**: Publish SHP files to GeoServer for WMS/WFS access
- **Layer Management**: Track layers, metadata, styling, visibility, opacity

## Architecture Layers

```
HTTP Layer (FastAPI endpoints)
    ↓
Use Cases (orchestration)
    ↓
Infrastructure (services, database, file storage)
    ↓
Domain (models, schemas)
```

- **Endpoints** (`api/v1/endpoints/`) — HTTP request handlers
- **Use Cases** (`usecases/`) — Business logic orchestration
- **Services** (`infrastructure/services/`) — File handling, tiling, GeoServer integration
- **Database** (`infrastructure/db/`) — SQLModel + Alembic migrations
- **Domain** (`domain/`) — Models, schemas, enums

## Key Workflows

### Upload & Tiling
1. File uploaded → `UploadSession` created with status=`uploaded`
2. User triggers tiling via `POST /uploads/{id}/tile`
3. Celery task queued → worker processes in background
4. Status transitions: `uploaded` → `processing` → `done` or `failed`
5. Tiles served from `/tiles/{layer_id}/{z}/{x}/{y}.png`

### GeoServer Publishing (SHP only)
1. File uploaded → `UploadSession` created
2. User triggers `POST /uploads/{id}/geoserver`
3. GeoServer REST API publishes file
4. Layer created with WMS/WFS URLs
5. Status transitions: `uploaded` → `processing` → `done` or `failed`

## Database

**Tables:**
- `upload_sessions` — file metadata, status, chunk tracking
- `layers` — layer configuration, URLs, styling, bbox

**Engines:** PostgreSQL (production), MySQL, SQLite (dev)

**Migrations:** Alembic with sequential naming (`0001_`, `0002_`, etc). Auto-applied on startup.

## Queue & Workers

- **Broker**: RabbitMQ (`amqp://...`)
- **Worker**: Celery daemon (`celery -A app.workers.celery_app worker`)
- **Tasks**: `process_tiling_task` — converts source file to tiles

## Environment

Key variables (see `.env.example`):
- `DB_TYPE`, `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` — database connection
- `RABBITMQ_URL` — RabbitMQ broker URL
- `CHUNK_UPLOAD_THRESHOLD` — direct upload size limit (default 10 MB)
- `GEOSERVER_URL`, `GEOSERVER_USER`, `GEOSERVER_PASSWORD` — GeoServer settings
- `BACKEND_CORS_ORIGINS` — allowed CORS origins

## Stack

- **Framework**: FastAPI 0.104+
- **ORM**: SQLModel (SQLAlchemy + Pydantic)
- **Queue**: Celery + RabbitMQ
- **Migrations**: Alembic
- **Geospatial**: Geopandas, Rasterio, Fiona, GDAL, Mercantile
- **Tiling**: Custom VectorTiler + RasterTiler classes
- **Database**: PostgreSQL + PostGIS (production)

## Next Steps

- [API Documentation](API.md) — Endpoint reference
- [Architecture](ARCHITECTURE.md) — Deep dive into components
- [Setup & Installation](SETUP.md) — Environment configuration
- [Development Guide](DEVELOPMENT.md) — Contributing, debugging, migration patterns
