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

Releases are fully managed by [semantic-release](https://semantic-release.gitbook.io/semantic-release/). On every push to `main` or `master`, it analyzes Conventional Commit messages, calculates the next semantic version, creates the Git tag and GitHub Release, and generates release notes. Git tags have no `v` prefix, such as `0.0.1`.

Use Conventional Commits in changes merged to a release branch:

- `fix: correct tile cache key` creates a patch release.
- `feat: add vector tile export` creates a minor release.
- `feat!: remove legacy tile endpoint` or a `BREAKING CHANGE:` footer creates a major release.
- Other commit types, such as `docs:` and `chore:`, do not create a release by themselves.

No version field, Git tag, or release needs to be created manually. `make docker-build` derives its image tag from the latest semantic Git tag; for example, Git tag `0.0.2` produces `tileserver:0.0.2`. Before the first release, it uses `tileserver:0.0.0`.

Each new release also builds and pushes `ghcr.io/muhamadanjar/tileserver:<version>` and `ghcr.io/muhamadanjar/tileserver:latest`. The workflow checks out the shared `muhamadanjar/service_auth` library; if that repository is private, configure a `SERVICE_AUTH_TOKEN` repository secret with read access to it.

Build the current image locally with:

```bash
make docker-build
```

The workflow configuration is [`.github/workflows/semantic-release.yml`](.github/workflows/semantic-release.yml), and the semantic-release configuration is [`.releaserc.json`](.releaserc.json).

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
