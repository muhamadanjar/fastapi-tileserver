# API Reference

Base URL: `http://localhost:8080/api/v1`

## Direct Upload

### POST `/upload`

Upload small file (< 10 MB) directly. File saved and UploadSession created. No automatic tiling.

**Request:**
```bash
curl -X POST http://localhost:8080/api/v1/upload \
  -F "file=@map.geojson" \
  -F "output_format=raster" \
  -F "max_zoom=14"
```

**Form Fields:**
- `file` (required) — geospatial file
- `output_format` (optional, default=`raster`) — `raster` or `mvt`
- `max_zoom` (optional) — max zoom level for tiling

**Response (201):**
```json
{
  "upload_id": "uuid-here",
  "layer_id": "generated-layer-id",
  "status": "uploaded",
  "message": "File uploaded successfully"
}
```

**Error Responses:**
- `413 Payload Too Large` — file exceeds threshold
- `415 Unsupported Media Type` — unsupported file format

---

## Chunked Upload

### POST `/uploads/init`

Initialize chunked upload session. Returns upload_id and chunk_size.

**Request:**
```bash
curl -X POST http://localhost:8080/api/v1/uploads/init \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "large_dataset.shp",
    "total_size": 1073741824,
    "output_format": "raster",
    "max_zoom": 15
  }'
```

**Body:**
```json
{
  "filename": "string (required)",
  "total_size": 123456789,
  "output_format": "raster or mvt (optional, default=raster)",
  "max_zoom": 14
}
```

**Response (201):**
```json
{
  "upload_id": "uuid-here",
  "layer_id": "generated-layer-id",
  "message": "Chunked upload session created...",
  "chunk_size": 10485760,
  "total_chunks": 103
}
```

---

### PATCH `/uploads/{upload_id}`

Upload single chunk. Use `Content-Range` header to identify position.

**Request:**
```bash
curl -X PATCH http://localhost:8080/api/v1/uploads/abc-123-def \
  -H "Content-Range: bytes 0-10485759/1073741824" \
  --data-binary @chunk1.bin
```

**Headers:**
- `Content-Range` (required) — `bytes START-END/TOTAL`
  - Example: `bytes 0-10485759/1073741824` (first 10 MB chunk of 1 GB file)

**Response (200):**
```json
{
  "chunk_index": 0,
  "uploaded_bytes": 10485760,
  "total_received": 10485760,
  "status": "uploading",
  "message": "Chunk received"
}
```

On **last chunk** (uploaded_bytes == total_size):
```json
{
  "chunk_index": 102,
  "uploaded_bytes": 10485760,
  "total_received": 1073741824,
  "status": "uploaded",
  "message": "Upload complete. All chunks received and assembled.",
  "final_path": "/path/to/data/uploads/filename"
}
```

**Error Responses:**
- `404 Not Found` — upload_id doesn't exist
- `400 Bad Request` — invalid Content-Range, wrong byte range
- `409 Conflict` — session already completed or expired

---

### GET `/uploads/{upload_id}/status`

Check upload progress and status.

**Request:**
```bash
curl http://localhost:8080/api/v1/uploads/abc-123-def/status
```

**Response:**
```json
{
  "upload_id": "abc-123-def",
  "layer_id": "layer-xyz",
  "filename": "large_dataset.shp",
  "status": "uploading",
  "received_bytes": 314572800,
  "total_size": 1073741824,
  "percentage": 29.3,
  "total_chunks": 103,
  "uploaded_chunks": 30
}
```

**Statuses:**
- `uploading` — chunks being received
- `uploaded` — all chunks received, ready to tile/publish
- `processing` — tiling or GeoServer publish in progress
- `done` — completed successfully
- `failed` — error occurred (check `error_message`)
- `expired` — session timeout exceeded

---

## Tiling

### POST `/uploads/{upload_id}/tile`

Trigger tile generation for uploaded file. File must be in `uploaded` or `failed` status.

**Request:**
```bash
curl -X POST "http://localhost:8080/api/v1/uploads/abc-123-def/tile?output_format=raster&max_zoom=14"
```

**Query Parameters:**
- `output_format` (optional) — override session default: `raster` or `mvt`
- `max_zoom` (optional) — override session default

**Response (200):**
```json
{
  "message": "Tiling started",
  "upload_id": "abc-123-def",
  "layer_id": "layer-xyz",
  "status": "processing"
}
```

After completion, status becomes `done` and `tile_url_template` is populated:
```
/tiles/{layer_id}/{z}/{x}/{y}.png
```

**Error Responses:**
- `404 Not Found` — upload not found
- `409 Conflict` — can't tile from current status
- `400 Bad Request` — assembled file missing

---

### GET `/tiles/{layer_id}/{z}/{x}/{y}.png`

Retrieve tile image. Returns PNG file.

**Request:**
```bash
curl -O http://localhost:8080/tiles/layer-xyz/12/2048/1024.png
```

**Response:**
- `200 OK` — PNG image binary
- `404 Not Found` — tile doesn't exist

---

## GeoServer Publishing

### POST `/uploads/{upload_id}/geoserver`

Publish SHP file to GeoServer. Creates workspace, datastore, featureType; returns WMS/WFS URLs.

**Request:**
```bash
curl -X POST http://localhost:8080/api/v1/uploads/abc-123-def/geoserver
```

**Requirements:**
- File must be `.shp` or `.zip` (containing `.shp`)
- GeoServer must be running and configured in `.env`
- File status must be `uploaded` or `failed`

**Response (200):**
```json
{
  "message": "GeoServer publish started",
  "upload_id": "abc-123-def",
  "layer_id": "layer-xyz",
  "status": "processing"
}
```

After completion (status = `done`), layer has:
```json
{
  "layer_type": "wms",
  "tile_url_template": "http://geoserver.example.com/geoserver/wms?...",
  "file_metadata": {
    "geoserver": {
      "workspace": "layers",
      "datastore": "layer-xyz",
      "featuretype": "geom",
      "wms_url": "http://...",
      "wfs_url": "http://..."
    }
  }
}
```

**Error Responses:**
- `404 Not Found` — upload not found
- `400 Bad Request` — file is not `.shp`/`.zip`
- `409 Conflict` — wrong status for publishing
- `502 Bad Gateway` — GeoServer connection failed

---

## Layer Management

### GET `/layers`

Fetch all layers (from dashboard or geoportal service). Not provided by tileserver, but layers are stored in `layers` table.

**Query Parameters:**
- `page` (optional, default=1) — pagination
- `limit` (optional, default=20) — items per page

**Response:**
```json
{
  "data": [
    {
      "id": "layer-xyz",
      "layer_type": "tile",
      "filename": "dataset.geojson",
      "tile_url_template": "/tiles/layer-xyz/{z}/{x}/{y}.png",
      "bbox_west": -120.5,
      "bbox_south": 30.2,
      "bbox_east": -100.3,
      "bbox_north": 45.1,
      "is_visible": true,
      "opacity": 0.8,
      "file_metadata": { ... }
    }
  ],
  "metas": {
    "page": 1,
    "limit": 20,
    "total": 5
  }
}
```

---

## Error Handling

All errors follow standard response format:

```json
{
  "status": "error",
  "message": "Human-readable error message",
  "data": null
}
```

**Common HTTP Status Codes:**
- `200 OK` — successful operation
- `201 Created` — resource created
- `400 Bad Request` — invalid input
- `404 Not Found` — resource not found
- `409 Conflict` — operation conflicts with current state
- `413 Payload Too Large` — file too large
- `415 Unsupported Media Type` — unsupported file format
- `500 Internal Server Error` — server error
- `502 Bad Gateway` — external service failure (GeoServer)

---

## Response Format (Standard)

All successful responses wrap data in:

```json
{
  "status": "success",
  "data": { ... },
  "metas": {
    "page": 1,
    "limit": 20,
    "total": 100
  },
  "message": "Optional message"
}
```

Errors wrap in:

```json
{
  "status": "error",
  "message": "Error description",
  "data": null
}
```

---

## Examples

### Complete Small Upload Flow
```bash
# 1. Upload file directly
curl -X POST http://localhost:8080/api/v1/upload \
  -F "file=@data.geojson"
# Returns: { "upload_id": "abc...", "status": "uploaded" }

# 2. Trigger tiling
curl -X POST http://localhost:8080/api/v1/uploads/abc/tile

# 3. Check status (poll until done)
curl http://localhost:8080/api/v1/uploads/abc/status
# Returns: { "status": "done" }

# 4. Fetch tiles
curl -O http://localhost:8080/tiles/layer-xyz/12/2048/1024.png
```

### Complete Large Upload Flow
```bash
# 1. Initialize chunked upload
curl -X POST http://localhost:8080/api/v1/uploads/init \
  -H "Content-Type: application/json" \
  -d '{"filename": "big.shp", "total_size": 1000000000}'
# Returns: { "upload_id": "def...", "chunk_size": 10485760 }

# 2. Upload chunks in parallel
for i in {0..99}; do
  START=$((i * 10485760))
  END=$(((i + 1) * 10485760 - 1))
  curl -X PATCH http://localhost:8080/api/v1/uploads/def \
    -H "Content-Range: bytes $START-$END/1000000000" \
    --data-binary @chunk$i.bin &
done
wait

# 3. Check status
curl http://localhost:8080/api/v1/uploads/def/status
# Returns: { "status": "uploaded" }

# 4. Trigger tiling
curl -X POST http://localhost:8080/api/v1/uploads/def/tile

# 5. Poll until done
while true; do
  STATUS=$(curl -s http://localhost:8080/api/v1/uploads/def/status | jq -r .data.status)
  [ "$STATUS" = "done" ] && break
  sleep 2
done

# 6. Fetch tiles
curl -O http://localhost:8080/tiles/layer-xyz/14/8192/4096.png
```
