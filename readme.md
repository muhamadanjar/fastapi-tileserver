# FastAPI TileServer

## Getting Started

### Prerequisites
- Python 3.11+
- Docker (for RabbitMQ)
- PostgreSQL (or MySQL/SQLite for dev)

### Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure environment:
```bash
cp .env.example .env
# Edit .env: DB_TYPE, DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
```

3. Start RabbitMQ (Docker):
```bash
docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management
```

4. Run FastAPI server (terminal 1) — auto-applies migrations:
```bash
uvicorn app.main:app --reload --port=8080
```

5. Run Celery worker (terminal 2):
```bash
celery -A app.workers.celery_app worker --loglevel=info --concurrency=4
```

API docs available at `http://localhost:8080/docs`

## Version Management

The release version is defined in `Makefile` as `VERSION` and follows semantic versioning: `MAJOR.MINOR.PATCH`. The current version is `0.0.1`.

To create a new release:

1. Update `VERSION` in `Makefile` (for example, `0.0.1` to `0.0.2`).
2. Commit the version change and push it to `main` or `master`.
3. The GitHub Actions workflow validates the version and creates a GitHub Release with the same value, such as `0.0.2`.

Do not add a `v` prefix. The GitHub release is `0.0.2`, and the corresponding Docker image is `tileserver:0.0.2`.

Build the current image locally with:

```bash
make docker-build
```

The workflow at [`.github/workflows/semantic-release.yml`](.github/workflows/semantic-release.yml) skips a release if that version already exists.

## Database Migrations

Migrations auto-run on app startup. Django-style sequential naming: `0001_`, `0002_`, etc.

### Create migration
```bash
# Auto-generates + renames with sequential number
./scripts/make_migration.sh "add status column to layers"
# Output: alembic/versions/0002_add_status_column_to_layers.py

# Or manual:
alembic revision -m "add status column to layers"
# Then rename file to 0002_add_status_column_to_layers.py
```

### Apply migrations
```bash
# Auto-applied on server startup
uvicorn app.main:app --reload

# Manual apply:
alembic upgrade head

# Check current version:
alembic current

# View migration history:
alembic history
```

### Rollback
```bash
# Rollback last migration:
alembic downgrade -1

# Rollback to specific version:
alembic downgrade 0001_initial_schema

# Rollback all:
alembic downgrade base
```

### Write migrations (example)
```python
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    # Add column
    op.add_column('layers', sa.Column('status', sa.String(), nullable=True))
    # Or create table, drop column, etc

def downgrade() -> None:
    op.drop_column('layers', 'status')
```

### Current schema
- `upload_sessions` — upload metadata, chunk tracking, status
- `layers` — layer config, visibility, styling, bbox
- FK: `layers.upload_session_id` → `upload_sessions.id`

See [CLAUDE.md](CLAUDE.md#database-migrations-alembic) for full migration docs.

## Usage Examples

### Direct upload (small file < 10 MB)
```bash
curl -X POST http://localhost:8080/api/v1/upload-and-tile \
  -F "file=@map.geojson" \
  -F "layer_id=my_layer"
```

### Chunked upload (large file)
```bash
# 1. Init upload
curl -X POST http://localhost:8080/api/v1/uploads/init \
  -H "Content-Type: application/json" \
  -d '{"filename":"large.shp","total_size":1073741824}'

# 2. Upload chunks with Content-Range header
curl -X PATCH http://localhost:8080/api/v1/uploads/{upload_id} \
  -H "Content-Range: bytes 0-10485759/1073741824" \
  --data-binary @chunk.bin

# 3. Check upload status
curl http://localhost:8080/api/v1/uploads/{upload_id}/status

# 4. Get tiles
curl http://localhost:8080/tiles/{layer_id}/{z}/{x}/{y}.png
```
