# Tiling Workflow Skill

## Purpose
Guide complete tiling process: upload geospatial data → process → serve tiles.

## Supported Formats
- **Vector:** `.shp`, `.geojson`, `.json`, `.gpkg`, `.kml`, `.zip` (containing `.shp`)
- **Raster:** `.tif`, `.tiff`, `.img`, `.png`, `.jpg`

## Workflow Steps

### 1. Upload Phase
**Small file (< 10 MB):**
```bash
POST /api/v1/upload
Content-Type: multipart/form-data

file: [geospatial_file]
```

**Large file (chunked, resumable):**
```bash
# Initialize
POST /api/v1/uploads/init
{ "filename": "data.shp", "total_size": 52428800 }
# → returns { upload_id, chunk_size, expected_chunks }

# Upload chunks (pause/resume safe)
PATCH /api/v1/uploads/{upload_id}
Content-Range: bytes 0-10485759/52428800
[binary chunk data]

# Check progress
GET /api/v1/uploads/{upload_id}/status
# → { status, received_bytes, total_size, progress_percent }
```

**Result:** `UploadSession` created with status `uploaded` (NOT auto-tiling)

### 2. Trigger Tiling
```bash
POST /api/v1/uploads/{upload_id}/tile
# → status changes to processing
# → Celery task queued to RabbitMQ
# → Returns immediately: { status: processing, ... }
```

### 3. Processing (Background Worker)
Celery worker receives task:
1. `TilingService.process_tiling()` reads source file
2. **Vector:** `VectorTiler.tile()` → Mapnik tiles
3. **Raster:** `RasterTiler.tile()` → reproject + GDAL tiles
4. Output: `data/tiles/{layer_id}/{z}/{x}/{y}.png`
5. Updates `UploadSession.status`:
   - ✅ `done` → `tile_url_template` populated
   - ❌ `failed` → `error_message` set

### 4. Serving Tiles
```bash
GET /tiles/{layer_id}/{z}/{x}/{y}.png
# → Serves PNG from data/tiles/{layer_id}/{z}/{x}/{y}.png
```

## Common Tasks

### Check Upload Status
```python
GET /api/v1/uploads/{upload_id}/status
```

### Retry Failed Tiling
```python
# Get UploadSession to see error_message
GET /api/v1/layers/{layer_id}

# Trigger tiling again (if file OK)
POST /api/v1/uploads/{upload_id}/tile
```

### List All Layers
```python
GET /api/v1/layers
```

### Delete Layer (& Tiles)
```bash
# Delete Layer record
DELETE /api/v1/layers/{layer_id}

# Clean up tile files
rm -rf data/tiles/{layer_id}/
```

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `Celery task never starts` | RabbitMQ/worker not running | `docker start rabbitmq` + `celery worker` |
| `File not found during tiling` | File not in `data/uploads/` | Check `prepare_source_path()` result |
| `Tiles not serving` | Wrong `tile_url_template` or files not in `data/tiles/` | Verify `Layer.tile_url_template` |
| `Invalid GeoTIFF` | Corrupt or unknown projection | Reproject to EPSG:3857 |
| `Unsupported format` | File extension not supported | Use supported formats only |

## Key Classes & Files
- `app/infrastructure/services/tiling_service.py` — orchestrator
- `app/infrastructure/services/file_service.py` — file validation & extraction
- `app/workers/tasks.py` — Celery task definition
- `app/api/v1/endpoints/upload.py` — upload endpoints
- `app/domain/models.py` — `UploadSession`, `Layer` schemas

## Rules
- **Manual tiling trigger only:** Upload creates session; user must call `POST /uploads/{upload_id}/tile`
- **Chunked uploads pauseable:** Can resume from any point; use `Content-Range` header
- **Worker async:** Tiling happens in background; check status via `GET /uploads/{upload_id}/status`
- **No auto-delete:** Tiles remain until manually deleted; use soft-delete for layers if needed
