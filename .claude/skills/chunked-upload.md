# Chunked Upload Skill

## Purpose
Upload large files with pause/resume support. Client can pause, disconnect, and resume from exact byte offset.

## When to Use
- Files **> 10 MB** (default `CHUNK_UPLOAD_THRESHOLD`)
- Network unreliable (pause/resume needed)
- Large geospatial datasets (raster GeoTIFF, large shapefiles)

## Flow

### 1. Initialize Upload
Client sends file metadata, server reserves upload slot:

```bash
POST /api/v1/uploads/init
Content-Type: application/json

{
  "filename": "large_map_50mb.shp",
  "total_size": 52428800
}
```

**Response:**
```json
{
  "upload_id": "abc-123-def-456",
  "chunk_size": 10485760,
  "expected_chunks": 5,
  "total_size": 52428800
}
```

**Server side:**
- `UploadSession` created with status `uploading`
- Directory created: `data/chunks/{upload_id}/`
- `chunk_map = {}` initialized (tracks received chunks)

### 2. Upload Chunks
Client sends file in `chunk_size` byte blocks (10 MB default):

```bash
# Chunk 1: bytes 0-10485759
PATCH /api/v1/uploads/{upload_id}
Content-Range: bytes 0-10485759/52428800
Content-Type: application/octet-stream

[binary chunk 1 data — exactly 10485760 bytes]
```

**Response:**
```json
{
  "upload_id": "abc-123-def-456",
  "status": "uploading",
  "received_bytes": 10485760,
  "total_size": 52428800,
  "progress_percent": 20
}
```

**Server side:**
- Chunk saved as: `data/chunks/{upload_id}/0.part`
- `chunk_map['0'] = true` (or last_modified timestamp)
- Client can now send chunk 2

### 3. Resume Paused Upload
If connection drops, client can resume:

```bash
# Check current progress
GET /api/v1/uploads/{upload_id}/status

# Response shows where to resume from
{
  "status": "uploading",
  "received_bytes": 10485760,  // resume from byte 10485760
  "total_size": 52428800
}

# Send next chunk from byte 10485760
PATCH /api/v1/uploads/{upload_id}
Content-Range: bytes 10485760-20971519/52428800
Content-Type: application/octet-stream

[binary chunk 2 data]
```

### 4. Assemble & Finalize (Automatic on 100%)
When `received_bytes == total_size`:

```bash
# Send final chunk
PATCH /api/v1/uploads/{upload_id}
Content-Range: bytes 41943040-52428799/52428800
[binary chunk 5 data — last 10485760 bytes]

# Response: status changes to uploaded
{
  "upload_id": "abc-123-def-456",
  "status": "uploaded",
  "received_bytes": 52428800,
  "total_size": 52428800,
  "progress_percent": 100,
  "layer_id": "layer-789"  // Layer record created
}
```

**Server side (automatic):**
1. `ChunkStorage.assemble()` concatenates parts: `0.part + 1.part + 2.part + 3.part + 4.part`
2. `FileService.prepare_source_path()` validates format, extracts ZIPs if needed
3. Final file saved to: `data/uploads/{upload_id}.shp` (or `.geojson`, `.tif`, etc)
4. Temp chunks cleaned: `rm -rf data/chunks/{upload_id}/`
5. `UploadSession.status → uploaded`
6. `Layer` record created with layer_id
7. Ready for tiling or GeoServer publish

## Content-Range Header Format

**Required format:**
```
Content-Range: bytes {start}-{end}/{total}
```

**Examples:**
```
Content-Range: bytes 0-10485759/52428800        # Chunk 1: bytes 0-10MB
Content-Range: bytes 10485760-20971519/52428800 # Chunk 2: bytes 10-20MB
Content-Range: bytes 41943040-52428799/52428800 # Chunk 5: bytes 40-50MB (last)
```

**Rules:**
- `{start}` = byte offset where chunk begins
- `{end}` = byte offset where chunk ends (inclusive)
- `{total}` = total file size (fixed for entire upload)
- Each chunk must be exactly `{end} - {start} + 1` bytes

## Out-of-Order Chunks

Server accepts chunks in any order:
```bash
# Send chunk 2
PATCH /api/v1/uploads/abc
Content-Range: bytes 10485760-20971519/52428800
[chunk 2 data]

# Send chunk 1
PATCH /api/v1/uploads/abc
Content-Range: bytes 0-10485759/52428800
[chunk 1 data]

# Send chunk 3
PATCH /api/v1/uploads/abc
Content-Range: bytes 20971520-31457279/52428800
[chunk 3 data]
```

Assembly happens **only** when all bytes received (detected by comparing `received_bytes == total_size`).

## Duplicate Chunk Handling

If client resends same chunk (network retry):

```bash
# Chunk 1 already received
PATCH /api/v1/uploads/abc
Content-Range: bytes 0-10485759/52428800
[same chunk 1 data again]

# Server: no-op, returns same status
{ "status": "uploading", "received_bytes": 10485760, ... }
```

Server ignores duplicate; no double-write or error.

## Error Cases

| Error | HTTP Code | Cause | Fix |
|-------|-----------|-------|-----|
| `Content-Range malformed` | 400 | Header format wrong | Use `bytes X-Y/Z` format |
| `Out of range` | 400 | Chunk overlaps/gaps | Check byte offsets align |
| `Upload expired` | 410 | Session > 7 days old | Restart upload with `POST /uploads/init` |
| `File validation failed` | 422 | Format invalid after assembly | Reupload; check file format |

## Timeout & Cleanup

- **Session expires:** 7 days (configurable)
- **Auto-cleanup:** Expired sessions deleted, chunk files removed
- **Manual cleanup:** Delete chunks if upload abandoned:
  ```bash
  rm -rf data/chunks/{upload_id}/
  DELETE /api/v1/uploads/{upload_id}  # (if endpoint exists)
  ```

## Storage Layout During Upload

```
data/
  chunks/
    {upload_id}/
      0.part        # 10 MB
      1.part        # 10 MB
      2.part        # 10 MB
      3.part        # 10 MB
      4.part        # 10 MB (last chunk, may be < 10 MB)
  uploads/          # (empty until assembly completes)
```

After assembly:
```
data/
  chunks/
    {upload_id}/    # (deleted)
  uploads/
    {upload_id}.shp
    {upload_id}.shx
    {upload_id}.dbf
    {upload_id}.prj
```

## Key Classes & Files
- `app/infrastructure/storage/chunk_storage.py` — `write_chunk()`, `assemble()`
- `app/infrastructure/services/file_service.py` — `prepare_source_path()`
- `app/api/v1/endpoints/upload.py` — POST/PATCH/GET endpoints
- `app/domain/models.py` — `UploadSession` with `chunk_map`

## Rules
- **Content-Range required:** All chunks must have header
- **Byte precision:** Offsets must match exactly; no gaps or overlaps
- **Assembly on 100%:** Server auto-assembles when total received
- **No server reassembly:** After assembly, don't call `/tile` until status = `uploaded`
- **Concurrent uploads OK:** Different `upload_id` can overlap without collision
