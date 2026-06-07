# Setup & Installation

## Prerequisites

- **Python** 3.11+
- **Docker** (for RabbitMQ)
- **PostgreSQL** (production) or SQLite (development)
- **GDAL** system library (for geospatial processing)

## Initial Setup

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

**Key packages:**
- `fastapi` 0.104+ — web framework
- `sqlmodel` — ORM (SQLAlchemy + Pydantic)
- `celery[amqp]` — task queue
- `geopandas` — vector processing
- `rasterio` — raster processing
- `alembic` — database migrations
- `mercantile` — tile math
- `python-multipart` — file upload handling

### 2. Configure Environment

Copy `.env.example` → `.env`:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```env
# Database
DB_TYPE=postgresql          # postgresql, mysql, sqlite
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=password
DB_NAME=tileserver_db

# Message Queue
RABBITMQ_URL=amqp://guest:guest@localhost:5672/

# Upload Settings
CHUNK_UPLOAD_THRESHOLD=10485760  # 10 MB in bytes
UPLOAD_DIR=./data/uploads
TILES_DIR=./data/tiles
CHUNKS_DIR=./data/chunks

# GeoServer (optional)
GEOSERVER_URL=http://localhost:8080/geoserver
GEOSERVER_USER=admin
GEOSERVER_PASSWORD=geoserver
GEOSERVER_WORKSPACE=layers

# CORS
BACKEND_CORS_ORIGINS=http://localhost:3000,http://localhost:8000
```

### 3. Create Database

**PostgreSQL:**
```bash
psql -U postgres
CREATE DATABASE tileserver_db;
\q
```

**MySQL:**
```bash
mysql -u root -p
CREATE DATABASE tileserver_db;
EXIT;
```

**SQLite (dev only):**
```bash
# Auto-created by SQLAlchemy on first connection
```

### 4. Run Database Migrations

Migrations auto-run on app startup. To manually apply:

```bash
alembic upgrade head
```

Check migration status:
```bash
alembic current    # shows applied version
alembic history    # shows all versions
```

### 5. Start RabbitMQ (Docker)

```bash
# Pull image
docker pull rabbitmq:3-management

# Run container
docker run -d \
  --name rabbitmq \
  -p 5672:5672 \
  -p 15672:15672 \
  rabbitmq:3-management

# Test connectivity
curl http://localhost:15672  # Management UI (guest/guest)
```

Verify connection from app:
```bash
python -c "import pika; conn = pika.BlockingConnection(pika.URLParameters('amqp://guest:guest@localhost:5672/')); conn.close(); print('OK')"
```

### 6. Create Data Directories

```bash
mkdir -p data/uploads data/tiles data/chunks
chmod -R 755 data/
```

## Running the Service

### Terminal 1: FastAPI Development Server

```bash
uvicorn app.main:app --reload --port 8080
```

**Output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8080
INFO:     Running migrations...
INFO:     Alembic upgrade head completed
```

Visit API docs: `http://localhost:8080/docs` (Swagger UI)

Alternative docs: `http://localhost:8080/redoc` (ReDoc)

Health check: `curl http://localhost:8080/`

### Terminal 2: Celery Worker

In a separate terminal (RabbitMQ must be running):

```bash
celery -A app.workers.celery_app worker --loglevel=info
```

**Output:**
```
Connected to amqp://guest:guest@localhost:5672/
 ---------- celery@hostname v5.x.x --------
[Tasks]
  . app.workers.tasks.process_tiling_task

[Worker Online]
```

If you see `ConnectionError`, check RabbitMQ is running:
```bash
docker ps | grep rabbitmq
docker logs rabbitmq
```

### Production Deployment

**FastAPI:**
```bash
# Gunicorn + Uvicorn workers (recommended)
gunicorn app.main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8080

# Or use Docker:
docker build -t tileserver-api .
docker run -d -p 8080:8080 tileserver-api
```

**Celery Worker:**
```bash
# Use supervisord or systemd to manage
celery -A app.workers.celery_app worker --loglevel=info --concurrency=4
```

**Database:**
- Use managed PostgreSQL (AWS RDS, Azure Database, GCP Cloud SQL)
- Backup strategy: automatic snapshots

**RabbitMQ:**
- Use managed service (CloudAMQP, AWS MQ)
- Or containerized: Docker Swarm / Kubernetes

## Troubleshooting Setup

### RabbitMQ Connection Fails

```
ConnectionError: [Errno 111] Connection refused
```

Check RabbitMQ is running:
```bash
docker ps | grep rabbitmq
docker start rabbitmq  # if not running
```

Or start fresh:
```bash
docker rm rabbitmq
docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management
```

### Database Connection Error

```
sqlalchemy.exc.OperationalError: [PostgreSQL] could not connect to server
```

Check PostgreSQL is running:
```bash
psql -U postgres -c "SELECT 1"  # test connection
```

Verify `.env` settings match your database.

### File Permissions

```
PermissionError: [Errno 13] Permission denied: 'data/uploads'
```

Fix ownership:
```bash
chmod -R 755 data/
chown -R $(whoami) data/  # if needed
```

### Missing GDAL

```
ImportError: GDAL/OGR not found
```

Install system library:

**Ubuntu/Debian:**
```bash
apt-get install gdal-bin libgdal-dev
```

**MacOS:**
```bash
brew install gdal
```

**Windows:**
```
Download from: https://trac.osgeo.org/osgeo4w/
```

Then reinstall Python packages:
```bash
pip install --upgrade --force-reinstall --no-cache-dir geopandas rasterio
```

### Alembic Migration Issues

Check applied migrations:
```bash
alembic current
```

View all versions:
```bash
alembic history
```

Rollback to specific version:
```bash
alembic downgrade 0001_initial_schema
```

Rollback last:
```bash
alembic downgrade -1
```

If database locked (SQLite):
```bash
# Close all connections, delete database, restart
rm tileserver_db.sqlite
alembic upgrade head
```

## Verification

Once setup is complete, verify all components:

```bash
# 1. FastAPI health check
curl http://localhost:8080/
# Expected: {"status":"ok"} or similar

# 2. RabbitMQ connectivity
curl http://localhost:15672  # management UI
# Expected: login page (guest/guest)

# 3. Database connection
psql -U postgres -d tileserver_db -c "SELECT COUNT(*) FROM upload_sessions;"
# Expected: 0 rows

# 4. API documentation
open http://localhost:8080/docs
```

### Test Upload

```bash
# Create small test file
echo '{"type":"FeatureCollection","features":[]}' > test.geojson

# Upload directly
curl -X POST http://localhost:8080/api/v1/upload \
  -F "file=@test.geojson"

# Expected: {"status":"success","data":{"upload_id":"...","status":"uploaded"}}
```

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `DB_TYPE` | postgresql | Database type: postgresql, mysql, sqlite |
| `DB_HOST` | localhost | Database host |
| `DB_PORT` | 5432 | Database port |
| `DB_USER` | postgres | Database user |
| `DB_PASSWORD` | password | Database password |
| `DB_NAME` | tileserver_db | Database name |
| `RABBITMQ_URL` | amqp://guest:guest@localhost:5672/ | RabbitMQ connection |
| `CHUNK_UPLOAD_THRESHOLD` | 10485760 | Max bytes for direct upload (10 MB) |
| `UPLOAD_DIR` | ./data/uploads | Directory for uploaded files |
| `TILES_DIR` | ./data/tiles | Directory for tile output |
| `CHUNKS_DIR` | ./data/chunks | Directory for chunk storage |
| `GEOSERVER_URL` | http://localhost:8080/geoserver | GeoServer URL |
| `GEOSERVER_USER` | admin | GeoServer user |
| `GEOSERVER_PASSWORD` | geoserver | GeoServer password |
| `GEOSERVER_WORKSPACE` | layers | GeoServer workspace |
| `BACKEND_CORS_ORIGINS` | (empty) | Comma-separated CORS origins |

## Next Steps

- [API Documentation](API.md) — endpoints and examples
- [Development Guide](DEVELOPMENT.md) — contributing, debugging, migrations
- [Architecture](ARCHITECTURE.md) — deep dive into components
