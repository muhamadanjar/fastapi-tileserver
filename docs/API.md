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
  "tile_url_template": "http://geoserver.example.com/geoserver/tileserver/wms",
  "bbox": [106.66, -6.57, 106.67, -6.56],
  "file_metadata": {
    "geoserver": {
      "layer_name": "tileserver:layer-xyz",
      "store_name": "layer-xyz",
      "workspace": "tileserver",
      "wms_url": "http://.../geoserver/tileserver/wms",
      "wfs_url": "http://.../geoserver/tileserver/wfs",
      "bbox": [106.66, -6.57, 106.67, -6.56],
      "crs": "EPSG:4326"
    },
    "layers": "tileserver:layer-xyz"
  }
}
```

**Bounding box (penting untuk tampil di peta):**
- Setelah datastore dibuat, service memanggil REST
  `PUT featuretypes/{store}.json?recalculate=nativebbox,latlonbbox` — paksa GeoServer
  hitung ulang bbox featuretype (mencegah bbox kosong di GeoServer)
- `Layer.bbox` di DB: prioritas extract dari file lokal, fallback `latLonBoundingBox`
  hasil recalculate GeoServer
- Tanpa bbox, frontend tidak bisa zoom-to-layer → layer terlihat "tidak muncul"

**Akses anonim (GeoNode GeoServer / GeoFence):**
GeoServer build GeoNode memakai GeoFence; tanpa rule, semua request OWS anonim
ditolak (`LayerNotDefined`, GetCapabilities kosong). Perlu rule ALLOW service=WMS:
```bash
curl -u admin:geoserver -X POST -H "Content-Type: application/json" \
  -d '{"Rule":{"priority":0,"access":"ALLOW","service":"WMS"}}' \
  http://localhost:8001/geoserver/rest/geofence/rules
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

### GET `/layers/{layer_id}/fields`

Daftar field/atribut layer — dipakai dialog Field Settings di dashboard.
Handler: `GetLayerFieldsUseCase` (`app/usecases/get_layer_fields.py`).

**Sumber field per tipe layer:**

| Tipe | Sumber |
|---|---|
| vector lokal (tile/mvt/geojson/kml) | kolom file sumber (geopandas) |
| raster lokal | `band_1..band_N` (rasterio) |
| external WMS (publish flow, source masih ada) | kolom file sumber lokal |
| external WMS (registrasi manual) | remote WFS `DescribeFeatureType` (pola GeoServer); gagal → `fields: []` |
| external lain (wmts/esri/...) | `404` |

**Response (200):**
```json
{
  "layer_id": "layer-xyz",
  "fields": ["id", "kabupaten", "kecamatan", "desa", "luas_m"]
}
```

**Error Responses:**
- `404 Not Found` — layer tidak ada, source file hilang, atau tipe layer tidak didukung

---

### GET `/layers/{layer_id}/features?lon=&lat=`

Query feature di koordinat (get info / click). Handler: `QueryLayerFeaturesUseCase`.

**Catatan WMS GetFeatureInfo:**
- BBOX query `±0.005°` di sekitar titik klik (resolusi ~2 m/pixel) — fitur kecil tetap match
- WMS 1.3.0 + EPSG:4326 → bbox axis order **lat,lon**; 1.1.1 → lon,lat
- Field config `file_metadata.fields` diterapkan ke semua tipe layer (visible only)

---

### GET `/layers/{layer_id}/style`

Ambil style tersimpan (editor state) untuk layer WMS yang dipublish ke GeoServer. Lihat `docs/STYLE_EDITING.md` untuk detail lengkap.

**Response (200):**
```json
{
  "layer_id": "98aa7ae4-e06e-4f9a-ab60-71d13416d728",
  "style_name": "layer_98aa7ae4-e06e-4f9a-ab60-71d13416d728",
  "style": null
}
```

**Error Responses:**
- `404 Not Found` — layer tidak ditemukan
- `422 Unprocessable Entity` — layer bukan WMS yang dipublish ke GeoServer (mis. external WMS atau tipe lain)

---

### PUT `/layers/{layer_id}/style`

Set style layer WMS GeoServer — dua mode: `simple` (JSON geometry-keyed, backend generate SLD 1.0.0) atau `sld` (raw SLD XML). Style disimpan di GeoServer sebagai `layer_{layer_id}` dan diset sebagai default style layer tersebut. Lihat `docs/STYLE_EDITING.md` untuk skema lengkap dan aturan editor-state vs rendering-truth.

**Request body — mode `simple`:**
```json
{
  "mode": "simple",
  "style": {
    "Polygon": {"fillColor": "#ff0000", "strokeColor": "#000000", "strokeWidth": 2, "opacity": 0.6, "strokePattern": "dashed", "fillPattern": "hatched"}
  }
}
```

**Request body — mode `sld`:**
```json
{
  "mode": "sld",
  "sld_body": "<sld:StyledLayerDescriptor xmlns:sld=\"http://www.opengis.net/sld\" version=\"1.0.0\">...</sld:StyledLayerDescriptor>"
}
```

**Response (200):** full `LayerResponse` (updated `file_metadata.style`).

**Error Responses:**
- `404 Not Found` — layer tidak ditemukan
- `422 Unprocessable Entity` — layer bukan WMS yang dipublish ke GeoServer; `style`/`sld_body` hilang atau tidak valid; unknown geometry key; SLD XML malformed; atau GeoServer menolak SLD (invalid content)
- `502 Bad Gateway` — GeoServer tidak bisa dihubungi atau gagal memproses request

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
