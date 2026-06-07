# TileServer API Documentation

Comprehensive documentation for FastAPI geospatial tile service.

## Quick Start

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
- **GeoServer** → SHP published to external GeoServer instance

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
  └── DEVELOPMENT.md      # Contributing guide + debugging
```

## Stack

- **Backend**: FastAPI 0.104+
- **ORM**: SQLModel (SQLAlchemy + Pydantic)
- **Queue**: Celery + RabbitMQ
- **Database**: PostgreSQL + PostGIS (or MySQL/SQLite)
- **Geospatial**: Geopandas, Rasterio, Mercantile, GDAL
- **Migrations**: Alembic

## Getting Help

**API questions:** [API Reference](API.md)

**Architecture questions:** [Architecture Deep Dive](ARCHITECTURE.md)

**Setup issues:** [Troubleshooting](SETUP.md#troubleshooting-setup)

**Development help:** [Development Guide](DEVELOPMENT.md)

**Code issues:** Check [CLAUDE.md](../CLAUDE.md) in project root (internal development notes)

---

Last updated: 2026-06-07
