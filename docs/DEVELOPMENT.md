# Development Guide

## Project Structure Review

See [Architecture](ARCHITECTURE.md) for detailed component breakdown.

Quick overview:
```
app/
  ├── api/v1/endpoints/       # HTTP handlers
  ├── usecases/               # Business logic orchestration
  ├── infrastructure/         # Services, DB, file storage
  ├── domain/                 # Models, schemas, enums
  ├── workers/                # Celery tasks
  └── core/                   # Config, response, exceptions
alembic/
  └── versions/               # Database migration files
data/
  ├── uploads/                # Final uploaded files
  ├── tiles/                  # Generated tile PNGs
  └── chunks/                 # Temporary chunk parts
```

## Development Workflow

### 1. Running Tests

No automated test suite configured. Manual testing recommended.

**Test direct upload:**
```bash
curl -X POST http://localhost:8080/api/v1/upload \
  -F "file=@sample.geojson"
```

**Test chunked upload:**
```bash
# 1. Init
curl -X POST http://localhost:8080/api/v1/uploads/init \
  -H "Content-Type: application/json" \
  -d '{"filename": "test.shp", "total_size": 1000000}'

# 2. Upload chunks
curl -X PATCH http://localhost:8080/api/v1/uploads/{upload_id} \
  -H "Content-Range: bytes 0-99999/1000000" \
  --data-binary @chunk1.bin

# 3. Check status
curl http://localhost:8080/api/v1/uploads/{upload_id}/status

# 4. Trigger tiling
curl -X POST http://localhost:8080/api/v1/uploads/{upload_id}/tile
```

### 2. Code Changes

**Add new endpoint:**
1. Create handler in `api/v1/endpoints/`
2. Add Pydantic request/response models to `domain/schemas.py`
3. Use dependency injection via `Depends()` for services
4. Follow standard response format (see `core/response.py`)

**Example:**
```python
# api/v1/endpoints/new_feature.py
from fastapi import APIRouter, Depends, HTTPException
from app.domain.schemas import MyRequest, MyResponse

router = APIRouter(prefix="/feature", tags=["feature"])

@router.post("/action", response_model=MyResponse)
async def my_action(body: MyRequest):
    # business logic
    return MyResponse(...)
```

Register in `app/main.py`:
```python
from app.api.v1.endpoints import new_feature
app.include_router(new_feature.router, prefix="/api/v1")
```

**Add new service:**
1. Create class in `infrastructure/services/`
2. Implement pure functions (no FastAPI coupling)
3. Inject into use cases via constructor

**Example:**
```python
# infrastructure/services/my_service.py
class MyService:
    def some_operation(self, data):
        # pure logic
        return result
```

**Add new use case:**
1. Create class in `usecases/`
2. Async `execute()` method
3. Use services + repository internally

**Example:**
```python
# usecases/my_usecase.py
class MyUseCase:
    def __init__(self, service: MyService, repo: MyRepository):
        self.service = service
        self.repo = repo
    
    async def execute(self, input_data):
        # orchestrate
        return result
```

### 3. Database Migrations

**Create migration:**
```bash
# Auto-generates + renames
./scripts/make_migration.sh "add column to layers"
# Creates: alembic/versions/0003_add_column_to_layers.py

# Or manual:
alembic revision -m "add column to layers"
# Then rename file to: 0003_add_column_to_layers.py
```

**Write migration:**
```python
# alembic/versions/0003_add_column_to_layers.py
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.add_column('layers', sa.Column('new_field', sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column('layers', 'new_field')
```

**Apply migration:**
```bash
alembic upgrade head
```

**Rollback:**
```bash
alembic downgrade -1  # last migration
alembic downgrade 0002_previous_migration  # to specific version
```

**View migration history:**
```bash
alembic history
alembic current
```

See [CLAUDE.md](../CLAUDE.md#database-migrations-alembic) for full migration docs.

### 4. Adding New File Formats

**Extend FileService.validate_format():**
```python
# infrastructure/services/file_service.py
SUPPORTED_VECTOR = ['.shp', '.geojson', '.json', '.gpkg', '.kml', '.gpx']
SUPPORTED_RASTER = ['.tif', '.tiff', '.img', '.png', '.jpg', '.geotiff']

def validate_format(self, filename):
    ext = Path(filename).suffix.lower()
    if ext in SUPPORTED_VECTOR:
        return 'vector'
    elif ext in SUPPORTED_RASTER:
        return 'raster'
    else:
        raise UnsupportedFileFormatException(...)
```

**Update tiling logic:**
- `VectorTiler` — for vector formats (uses geopandas)
- `RasterTiler` — for raster formats (uses rasterio)

Both inherit from base tiler class pattern or standalone.

### 5. Debugging

**Enable verbose logging:**
```bash
# FastAPI
uvicorn app.main:app --reload --log-level debug

# Celery worker
celery -A app.workers.celery_app worker --loglevel=debug

# Alembic
alembic upgrade head --sql  # shows SQL without running
```

**Inspect database:**
```bash
# PostgreSQL
psql -U postgres -d tileserver_db
SELECT * FROM upload_sessions;
SELECT * FROM layers;

# SQLite
sqlite3 tileserver_db.sqlite
.schema
.tables
SELECT * FROM upload_sessions;
```

**Check file system:**
```bash
ls -lR data/uploads/     # uploaded files
ls -lR data/tiles/       # generated tiles
ls -lR data/chunks/      # chunk parts (temp)
```

**Monitor RabbitMQ:**
```bash
# Management UI
open http://localhost:15672  # guest/guest

# CLI
docker exec rabbitmq rabbitmqctl list_connections
docker exec rabbitmq rabbitmqctl list_channels
docker exec rabbitmq rabbitmqctl list_queues
```

### 6. Code Style

**No formatter/linter configured.** Recommendations:

```bash
# Install (optional)
pip install black flake8 isort

# Format
black app/
isort app/

# Lint
flake8 app/ --max-line-length=120
```

**Python conventions:**
- Use type hints (`def func(x: int) -> str:`)
- Async for I/O operations in FastAPI
- Sync for services (pure logic)
- Follow Clean Architecture layers (no cross-layer imports)

### 7. Performance Tips

**Chunked upload optimization:**
- Set `CHUNK_UPLOAD_THRESHOLD` based on available RAM
- Default 10 MB suitable for most cases
- Increase for high-concurrency deployments

**Tiling optimization:**
- `VectorTiler` uses spatial index (`gdf.sindex`) for fast lookups
- `RasterTiler` uses memory-mapped files via rasterio
- Tile generation parallelizes across zoom levels (single-threaded per tile)

**Database optimization:**
- Use PostgreSQL + PostGIS for production
- Add indices on frequently queried columns (already done for PK/FK)
- Connection pooling via SQLAlchemy (default)

**API response caching:**
- Tile PNGs served statically (no caching headers needed)
- Status responses not cached (always fresh)
- Consider CDN for `/tiles/` endpoints in production

### 8. Security Considerations

**File uploads:**
- Validate file type by extension + magic bytes (FileService does extension)
- Limit file size via `CHUNK_UPLOAD_THRESHOLD`
- Sanitize layer_id (slugify filename, no path traversal)

**Database:**
- Use parameterized queries (SQLModel/SQLAlchemy does this)
- Connection credentials in `.env` (not hardcoded)
- Don't expose raw SQL in error messages

**API:**
- CORS configured via `BACKEND_CORS_ORIGINS`
- No authentication implemented (add if needed)
- Rate limiting (consider FastAPI-Limiter)

**File system:**
- Store uploads outside web root
- Set restrictive permissions: `chmod -R 755 data/`
- Don't serve arbitrary files

### 9. Error Handling

**Custom exceptions** in `core/exceptions.py`:
```python
class ChunkUploadError(Exception)
class SessionNotFoundError(Exception)
class TilingProcessError(Exception)
```

**HTTP error responses:**
```python
from fastapi import HTTPException

raise HTTPException(
    status_code=400,
    detail="Human-readable error message"
)
```

**Celery task errors:**
```python
try:
    result = tiling_service.process_tiling(...)
except TilingProcessError as exc:
    await repo.set_status(upload_id, JobStatus.failed, str(exc))
```

### 10. Extending with GeoServer

**Current integration:**
- `POST /uploads/{id}/geoserver` publishes SHP to GeoServer
- Requires GeoServer running + credentials in `.env`

**To add new GeoServer features:**
1. Extend `GeoServerService` class
2. Add new method (e.g., `publish_kml()`)
3. Create endpoint in `api/v1/endpoints/`
4. Update Layer record with results

**Example:**
```python
# infrastructure/services/geoserver_service.py
def publish_kml(self, file_path, store_name):
    # upload to GeoServer
    # create featureType
    # return WMS URL
    pass
```

## Common Tasks

### Add Authentication

1. Install: `pip install fastapi-security python-jose passlib`
2. Create `auth/security.py` with JWT logic
3. Add dependency to endpoints: `Depends(verify_token)`
4. Update `.env` with secret key

### Add Rate Limiting

1. Install: `pip install slowapi`
2. Configure limiter in `main.py`
3. Decorate endpoints: `@limiter.limit("10/minute")`

### Add Monitoring/Logging

1. Install: `pip install python-json-logger`
2. Configure logging in `main.py`
3. Send logs to ELK stack, Datadog, or CloudWatch

### Deploy to Docker

1. Create `Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app/ app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

2. Create `docker-compose.yml` with FastAPI + Celery + RabbitMQ + PostgreSQL
3. `docker-compose up`

### Scale Celery Workers

Multiple workers consume from same RabbitMQ queue:
```bash
# Terminal 2
celery -A app.workers.celery_app worker -l info --concurrency=4

# Terminal 3
celery -A app.workers.celery_app worker -l info --concurrency=4
```

RabbitMQ load-balances tasks automatically.

## Troubleshooting Development

### Changes not reflected after code edit

FastAPI reload might not pick up changes. Restart:
```bash
# Ctrl+C to stop
# Then restart
uvicorn app.main:app --reload
```

### Celery task stuck

Check worker logs:
```bash
celery -A app.workers.celery_app worker -l debug
```

Kill worker if frozen:
```bash
pkill -f "celery worker"
```

### Database locked (SQLite)

Multiple processes can't write simultaneously. Restart:
```bash
rm tileserver_db.sqlite  # if dev
alembic upgrade head     # recreate
```

### Tiles not generating

1. Check Celery worker is running: `celery ... worker`
2. Check RabbitMQ: `docker ps | grep rabbitmq`
3. Check logs: `celery ... worker -l debug`
4. Verify file exists: `ls -la data/uploads/{filename}`

## Next Steps

- [Setup & Installation](SETUP.md) — environment configuration
- [API Documentation](API.md) — endpoint reference
- [Architecture](ARCHITECTURE.md) — component deep dive
