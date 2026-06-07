# API Reference Skill

## Base URL
```
http://localhost:8000/api/v1
```

## Health Check
```bash
GET /
→ 200 OK { "status": "ok" }
```

## Upload Endpoints

### Direct Upload (Small Files)
```bash
POST /upload
Content-Type: multipart/form-data

file: [geospatial_file <= 10 MB]

Response:
{
  "status": 201,
  "data": {
    "upload_id": "uuid",
    "layer_id": "layer-uuid",
    "filename": "data.shp",
    "file_type": "shapefile",
    "status": "uploaded",
    "message": "File uploaded and ready for processing"
  }
}
```

### Initialize Chunked Upload
```bash
POST /uploads/init
Content-Type: application/json

{
  "filename": "large_file.tif",
  "total_size": 52428800
}

Response:
{
  "status": 201,
  "data": {
    "upload_id": "uuid",
    "chunk_size": 10485760,
    "expected_chunks": 5,
    "message": "Upload session initialized"
  }
}
```

### Upload Chunk
```bash
PATCH /uploads/{upload_id}
Content-Range: bytes 0-10485759/52428800
Content-Type: application/octet-stream

[binary chunk data]

Response:
{
  "status": 200,
  "data": {
    "upload_id": "uuid",
    "status": "uploading",
    "received_bytes": 10485760,
    "total_size": 52428800,
    "progress_percent": 20
  }
}
```

### Check Upload Status
```bash
GET /uploads/{upload_id}/status

Response:
{
  "status": 200,
  "data": {
    "upload_id": "uuid",
    "status": "uploading|uploaded|failed",
    "received_bytes": 10485760,
    "total_size": 52428800,
    "progress_percent": 20,
    "error_message": null
  }
}
```

## Tiling Endpoints

### Trigger Tiling
```bash
POST /uploads/{upload_id}/tile
Content-Type: application/json

{}

Response:
{
  "status": 202,
  "data": {
    "upload_id": "uuid",
    "layer_id": "uuid",
    "status": "processing",
    "message": "Tiling job queued"
  }
}
```

### Get Tiling Status
Via `GET /uploads/{upload_id}/status` (returns current UploadSession status)

## GeoServer Endpoints

### Publish to GeoServer (SHP Only)
```bash
POST /uploads/{upload_id}/geoserver
Content-Type: application/json

{}

Response:
{
  "status": 202,
  "data": {
    "upload_id": "uuid",
    "layer_id": "uuid",
    "status": "processing",
    "message": "GeoServer publish job queued"
  }
}
```

## Layer Endpoints

### List All Layers
```bash
GET /layers?skip=0&limit=100

Response:
{
  "status": 200,
  "data": {
    "layers": [
      {
        "id": "layer-uuid",
        "filename": "data.shp",
        "layer_type": "tiled|wms",
        "tile_url_template": "/tiles/layer-uuid/{z}/{x}/{y}.png",
        "bbox": [100.0, -10.0, 110.0, 0.0],
        "file_metadata": {
          "geoserver": { ... }  // if published to GeoServer
        },
        "created_at": "2026-06-07T10:30:00Z"
      }
    ],
    "total": 42
  },
  "meta": {
    "skip": 0,
    "limit": 100
  }
}
```

### Get Layer Details
```bash
GET /layers/{layer_id}

Response:
{
  "status": 200,
  "data": {
    "id": "layer-uuid",
    "filename": "data.shp",
    "layer_type": "tiled|wms",
    "tile_url_template": "/tiles/layer-uuid/{z}/{x}/{y}.png",
    "bbox": [100.0, -10.0, 110.0, 0.0],
    "visibility": true,
    "file_metadata": {
      "geoserver": {
        "workspace": "tileserver_workspace",
        "wms_url": "http://geoserver:8080/geoserver/wms?...",
        "wfs_url": "http://geoserver:8080/geoserver/wfs?..."
      }
    }
  }
}
```

### Update Layer Visibility
```bash
PATCH /layers/{layer_id}
Content-Type: application/json

{
  "visibility": false
}

Response:
{
  "status": 200,
  "data": { ... updated layer ... }
}
```

### Delete Layer
```bash
DELETE /layers/{layer_id}

Response:
{
  "status": 200,
  "data": {
    "message": "Layer deleted"
  }
}
```

**Note:** Does NOT delete tiles from disk; manual cleanup: `rm -rf data/tiles/{layer_id}/`

## Tiles Endpoint

### Get Tile PNG
```bash
GET /tiles/{layer_id}/{z}/{x}/{y}.png

Response: 200 [binary PNG data]
```

**Note:** `z` = zoom, `x` = longitude tile index, `y` = latitude tile index (Web Mercator TMS format)

## Response Format

All endpoints follow standard response:
```json
{
  "status": 200,
  "data": { ... },
  "meta": { ... },
  "message": "Success message"
}
```

- **status:** HTTP code
- **data:** Response payload (object or array)
- **meta:** Pagination (skip, limit, total) if applicable
- **message:** Optional string

## Error Response

```json
{
  "status": 400,
  "data": null,
  "message": "Error description"
}
```

## Common Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 202 | Accepted (async task queued) |
| 400 | Bad request (invalid input) |
| 404 | Not found |
| 410 | Gone (upload expired) |
| 422 | Unprocessable (validation failed) |
| 500 | Server error |

## Query Parameters

### Pagination
```bash
GET /layers?skip=0&limit=100
```

- `skip` (int, default 0): Records to skip
- `limit` (int, default 100): Records to return

## Environment / Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CHUNK_UPLOAD_THRESHOLD` | 10485760 | Byte limit for direct upload (10 MB) |
| `BACKEND_CORS_ORIGINS` | "" | Comma-separated CORS origins |
| `RABBITMQ_URL` | `amqp://guest:guest@localhost:5672/` | Celery broker URL |
| `REDIS_URL` | `redis://localhost:6379` | Optional Redis for caching |

## Swagger UI
```
http://localhost:8000/docs
```

## ReDoc
```
http://localhost:8000/redoc
```
