# TileServer API Documentation

Comprehensive documentation for FastAPI geospatial tile service.

## Quick Start

## Environment ownership

| Variable | Used by | Purpose |
|---|---|---|
| `UPLOAD_API_URL` | Tileserver API and workers | Upload API base URL used when processing an artifact handoff. |
| `UPLOAD_API_CALLER_TOKEN` | Tileserver API and workers | Static server-to-server bearer token sent to Upload API; must equal Upload API's `UPLOAD_API_TRUSTED_SERVICE_TOKENS["tileserver"]`. |
| `UPLOAD_API_SERVICE_TOKEN` | Tileserver API and workers | Deprecated fallback alias for `UPLOAD_API_CALLER_TOKEN`. |
| `DB_*`, `RABBITMQ_URL`, `REDIS_URL` | Tileserver API/workers | Database, background queue, and cache configuration. |
| `GEOSERVER_*` | Tileserver API/workers | GeoServer integration credentials and target workspace. |
| `CORS_ALLOWED_*` | Tileserver API | Browser origin and header policy. |

`UPLOAD_API_CALLER_TOKEN` is not a user JWT and must not be sent to the browser. See [the shared authentication contract](../../usermanagement_api/docs/features/authentication-and-authorization.md).

**New to TileServer?** Start here:
1. [Overview](OVERVIEW.md) — service purpose, features, architecture overview
2. [Setup](SETUP.md) — install dependencies, configure environment, run services

## Reference

**Using the API:**
- [API Reference](API.md) — all endpoints, request/response examples, error codes

**Understanding the Code:**
- [Architecture](ARCHITECTURE.md) — detailed component breakdown, data flows, design patterns
- [Development Guide](DEVELOPMENT.md) — contributing code, debugging, common tasks

## Common Tasks

### I want to...

**...set up locally**
→ [Setup: Initial Setup](SETUP.md#initial-setup)

**...understand the system**
→ [Overview](OVERVIEW.md) + [Architecture](ARCHITECTURE.md)

**...use the API**
→ [API Reference](API.md) (contains curl examples)

**...add a new feature**
→ [Development: Code Changes](DEVELOPMENT.md#2-code-changes)

**...create a database migration**
→ [Development: Database Migrations](DEVELOPMENT.md#3-database-migrations)

**...deploy to production**
→ [Setup: Production Deployment](SETUP.md#production-deployment)

**...debug an issue**
→ [Development: Debugging](DEVELOPMENT.md#5-debugging)

**...scale the system**
→ [Development: Scale Celery Workers](DEVELOPMENT.md#scale-celery-workers)

**...see recent changes**
→ [Recent Updates](RECENT_UPDATES.md)

**...query features from a layer**
→ [Feature Query Guide](FEATURE_QUERY.md)

**...cancel a tiling task**
→ [Recent Updates: Cancel Task](RECENT_UPDATES.md#1-cancel-task-feature)

## Recent Implementation (2026-06-10)

### ✅ Cancel Task Feature
- New endpoint: `POST /uploads/{upload_id}/cancel`
- New status: `JobStatus.cancelled` enum value
- Celery revoke + cooperative DB check
- Store task ID in `UploadSession.celery_task_id`
- Migration: `0003_add_celery_task_id_to_upload_sessions.py`

### ✅ Layer Code Uniqueness
- Remove file extension from code (slug filename only)
- Append `-1`, `-2`, etc. if code already exists
- Usecase: `generate_unique_code()` + `generate_unique_code_sync()`
- Applied to: external layers, GeoServer publish, tiling tasks

### ✅ GeoServer Store Name Fix
- Changed from `store_name = layer_id` (UUID) to `store_name = code` (slug)
- Rename .shp files in zip to match store_name
- Result: GeoServer layer_name = "workspace:code" (consistent with DB)
- Service: `GeoServerService._to_zip()` param `rename_to`

### ✅ WMS GetFeatureInfo Support
- New: Query endpoint now handle WMS layers
- Proxy WMS GetFeatureInfo requests
- Support: WMS 1.1.1 & 1.3.0
- Response format: same as local vector queries

### ✅ QueryLayerFeaturesUseCase Refactoring
- Centralized feature query logic
- File: `app/usecases/getinfo_layer.py`
- Support: vector (GeoPandas), raster (Rasterio), WMS, WFS
- Endpoint: `/layers/{layer_id}/features?lon=X&lat=Y`
- Removed inline query logic from endpoint

### ✅ WMS GetFeatureInfo Fix
- BBOX query ±0.005° (sebelumnya ±1° — fitur kecil sub-pixel, tidak match)
- WMS 1.3.0 + EPSG:4326: bbox axis order lat,lon (per spec)
- Detail: [Recent Updates §5](RECENT_UPDATES.md#5-wms-getfeatureinfo-fix)

### ✅ GetLayerFieldsUseCase + WMS Fields
- File: `app/usecases/get_layer_fields.py` (NEW)
- `GET /layers/{id}/fields` support layer WMS external (lokal / WFS DescribeFeatureType)
- Exceptions baru: `LayerNotFoundError`, `LayerFieldsUnavailableError`
- Detail: [Recent Updates §6](RECENT_UPDATES.md#6-layer-fields-untuk-wms--refactor-ke-usecase)

### ✅ GeoServer Publish BBox Recalculate
- `GeoServerService._recalculate_bbox()` — REST `recalculate=nativebbox,latlonbbox`
- DB bbox fallback dari GeoServer kalau extract file lokal gagal
- Detail: [Recent Updates §7](RECENT_UPDATES.md#7-geoserver-publish--bbox-recalculate)

## Architecture Overview

```
HTTP Layer (FastAPI endpoints)
    ↓
Use Cases (business logic)
    ↓
Services (file handling, tiling, database)
    ↓
Domain (models, schemas)
```

Data flows:
- **Upload** → `UploadSession` created with status=`uploaded`
- **Tiling** → Celery task queued, background processing, status → `done` or `failed`
- **Cancel** → Revoke task + set status=`cancelled`
- **GeoServer** → SHP published, store_name = code (slug)
- **Query Features** → UseCase dispatch by layer type (vector/raster/WMS/WFS)

## Key Concepts

**Upload Session** — tracks file upload progress, metadata, status
- Small files (< 10 MB): uploaded directly
- Large files: chunked, resumable, pause-friendly

**Layer** — represents processed data source
- Associated with upload session
- Contains tile URLs, styling, metadata, bbox
- Supports tile/mvt/wms/wfs layer types

**Tiling** — generates Web Mercator PNG tiles
- VectorTiler: vector data → tiles
- RasterTiler: raster data → tiles
- Automatic zoom level detection

**Queue** — background task processing
- Celery worker consumes tiling jobs
- RabbitMQ broker routes tasks
- Fire-and-forget (no persistent result backend)

## File Organization

```
docs/
  ├── README.md           # This file
  ├── OVERVIEW.md         # High-level introduction
  ├── API.md              # Endpoint reference + examples
  ├── ARCHITECTURE.md     # Component breakdown + data flows
  ├── SETUP.md            # Installation + configuration
  ├── DEVELOPMENT.md      # Contributing guide + debugging
  ├── RECENT_UPDATES.md   # Latest implementation (2026-06-10)
  └── FEATURE_QUERY.md    # Feature query details
```

## Stack

- **Backend**: FastAPI 0.104+
- **ORM**: SQLModel (SQLAlchemy + Pydantic)
- **Queue**: Celery + RabbitMQ
- **Database**: PostgreSQL + PostGIS (or MySQL/SQLite)
- **Geospatial**: Geopandas, Rasterio, Mercantile, GDAL
- **Migrations**: Alembic

## Getting Help

**Upload artifact handoff:** [Artifact Handoff](features/upload-artifact-handoff.md)

**API questions:** [API Reference](API.md)

**Architecture questions:** [Architecture Deep Dive](ARCHITECTURE.md)

**Setup issues:** [Troubleshooting](SETUP.md#troubleshooting-setup)

**Development help:** [Development Guide](DEVELOPMENT.md)

**Code issues:** Check [CLAUDE.md](../CLAUDE.md) in project root (internal development notes)

---

Last updated: 2026-06-07
