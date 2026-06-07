# GeoServer Publish Skill

## Purpose
Publish Shapefile (SHP) to GeoServer, manage WMS/WFS endpoints.

## Prerequisites
- **SHP files only** — vector files with sidecar files (`.shx`, `.dbf`, `.prj`)
- **GeoServer running** at `GEOSERVER_URL` from `.env`
- **Valid credentials:** `GEOSERVER_USER`, `GEOSERVER_PASSWORD` in `.env`
- **File must be uploaded first** via `POST /api/v1/upload` or chunked upload

## Setup

### Environment Variables
```bash
# .env
GEOSERVER_URL=http://localhost:8080/geoserver
GEOSERVER_USER=admin
GEOSERVER_PASSWORD=geoserver
GEOSERVER_WORKSPACE=tileserver_workspace
```

### GeoServer Quick Start
```bash
# Docker run GeoServer
docker run -d \
  --name geoserver \
  -p 8080:8080 \
  -e GEOSERVER_ADMIN_PASSWORD=geoserver \
  geosolutionsit/geoserver:latest

# Access: http://localhost:8080/geoserver
# Default: admin / geoserver
```

## Workflow

### 1. Validate SHP File
Before publishing, ensure:
- File is `.shp` (not raster or other format)
- Sidecar files exist: `.shx`, `.dbf`, `.prj`
- Projection defined in `.prj`
- File uploaded successfully (UploadSession status = `uploaded`)

```bash
# Check uploaded file
ls -la data/uploads/ | grep {upload_id}
# Should see: upload_id.shp, upload_id.shx, upload_id.dbf, upload_id.prj
```

### 2. Publish to GeoServer
```bash
POST /api/v1/uploads/{upload_id}/geoserver
Content-Type: application/json

{}
```

**Server actions:**
1. Creates GeoServer workspace (if not exists)
2. Uploads `.shp` + sidecar files to datastore
3. Creates featureType (layer definition)
4. Retrieves WMS/WFS URLs
5. Creates `Layer` record with GeoServer metadata
6. Updates `UploadSession.status` → `done` or `failed`

### 3. Fetch Published Layer
```bash
GET /api/v1/layers/{layer_id}

Response:
{
  "id": "layer-123",
  "filename": "data.shp",
  "layer_type": "wms",
  "tile_url_template": "http://localhost:8080/geoserver/wms?...",
  "file_metadata": {
    "geoserver": {
      "workspace": "tileserver_workspace",
      "datastore": "tileserver_workspace_store",
      "featuretype_name": "data",
      "wms_url": "http://localhost:8080/geoserver/wms?service=WMS&...",
      "wfs_url": "http://localhost:8080/geoserver/wfs?service=WFS&..."
    }
  }
}
```

### 4. Use WMS URL in Frontend
Frontend can fetch WMS tiles:
```
GET http://localhost:8080/geoserver/wms?
  service=WMS&
  version=1.1.0&
  request=GetMap&
  layers=tileserver_workspace:data&
  bbox={minx},{miny},{maxx},{maxy}&
  width=256&
  height=256&
  srs=EPSG:3857&
  format=image/png
```

## REST API Details

### Create Workspace
```
POST /rest/workspaces
Content-Type: application/json

{ "workspace": { "name": "tileserver_workspace" } }
```

### Upload SHP to Datastore
```
POST /rest/workspaces/{workspace}/datastores/{datastore}/file.shp
Content-Type: application/zip

[binary zip containing .shp + sidecars]
```

### Create FeatureType
```
POST /rest/workspaces/{workspace}/datastores/{datastore}/featuretypes
Content-Type: application/json

{
  "featureType": {
    "name": "data",
    "nativeName": "data",
    "title": "Data Layer"
  }
}
```

## Error Handling

| Error | Cause | Fix |
|-------|-------|-----|
| `GeoServer unreachable` | URL wrong or GeoServer down | Check `GEOSERVER_URL`, verify Docker running |
| `Workspace creation failed` | Workspace exists or auth failed | Check credentials, delete workspace in UI if exists |
| `SHP not supported` | File is not `.shp` | Use tiling for non-SHP formats |
| `Missing sidecar files` | `.shx`, `.dbf`, `.prj` missing | Ensure all 4 files uploaded (use `.zip` for safety) |
| `Invalid SHP structure` | Shapefile corrupt | Validate locally with `ogr2ogr` or QGIS |

## Failover

No automatic retry on first failure:
1. Check `UploadSession.error_message` for reason
2. Fix issue (credentials, GeoServer running, file valid)
3. Retry: `POST /api/v1/uploads/{upload_id}/geoserver` again

## Key Classes & Files
- `app/infrastructure/services/geoserver_service.py` — orchestrator
- `app/infrastructure/services/geoserver_client.py` — HTTP wrapper for REST API
- `app/api/v1/endpoints/upload.py` — `POST /geoserver` endpoint
- `app/domain/models.py` — `Layer` with `file_metadata.geoserver`

## Rules
- **Manual publish only:** Must explicitly call `POST /geoserver` endpoint (not automatic)
- **SHP files only:** Raster or non-SHP vectors use tiling instead
- **Metadata stored:** WMS/WFS URLs persisted in `Layer.file_metadata` for frontend access
- **No overwrite detection:** Publishing same file again will create duplicate layer in GeoServer
