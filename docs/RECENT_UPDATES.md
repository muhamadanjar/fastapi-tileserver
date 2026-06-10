# Recent Updates (2026-06-10)

Documentation of recent implementation changes.

## 1. Cancel Task Feature

### Endpoint
```
POST /uploads/{upload_id}/cancel
```

### Status Changes
- Added `cancelled` to `JobStatus` enum
- New status value: `"cancelled"`

### Implementation

**New DB column:** `UploadSession.celery_task_id: Optional[str]`
- Stores Celery task UUID for revocation
- Migration: `0003_add_celery_task_id_to_upload_sessions.py`

**Capture task ID:**
```python
# In trigger_tiling endpoint
task = process_tiling_task.delay(...)
await repo.set_task_id(upload_id, task.id)  # NEW
```

**Cancel logic:**
```python
# Revoke task if in-flight
if session.celery_task_id:
    celery_app.control.revoke(task_id, terminate=True, signal='SIGTERM')

# Update status
await repo.set_status(upload_id, JobStatus.cancelled)
```

**Cooperative cancel in worker:**
```python
# Check if cancelled before start
current = repo.get_by_id(upload_id)
if current and current.status == JobStatus.cancelled:
    return  # abort early

# Don't overwrite cancelled status with failed
if current.status != JobStatus.cancelled:
    repo.set_status(upload_id, JobStatus.failed, ...)
```

### Guard Conditions
- Only cancel from: `{uploaded, pending, processing}` status
- Return 409 if current status not cancellable
- Idempotent: can call multiple times safely

---

## 2. Layer Code Uniqueness

### Problem
- Multiple layers with same filename → duplicate codes
- GeoServer store names not unique
- Data inconsistency

### Solution
- Generate unique code with `-1`, `-2`, etc. suffix if exists
- Check all created codes against database
- Applied consistently across all layer creation paths

### Implementation

**Usecase:** `generate_unique_code()` (async) + `generate_unique_code_sync()` (sync)

```python
async def generate_unique_code(
    base_slug: str,
    check_exists: Callable[[str], Awaitable[bool]]
) -> str:
    code = base_slug
    sequence = 1
    while await check_exists(code):
        code = f"{base_slug}-{sequence}"
        sequence += 1
    return code
```

**File extension removed:**
- Before: "PT Rifijaya Sejati.zip" → "pt-rifijaya-sejati-zip"
- After: "PT Rifijaya Sejati.zip" → "pt-rifijaya-sejati"
- Uses `Path(filename).stem` before slug

**Applied to:**
1. External layer creation (`/api/v1/layers/external`)
2. GeoServer publish (`/api/v1/uploads/{id}/geoserver`)
3. Tiling placeholder layer (worker)
4. Tiling final layer (worker)

**Repository methods:**
- `LayerRepository.code_exists(code: str) -> bool` (async)
- `SyncLayerRepository.code_exists(code: str) -> bool` (sync)

---

## 3. GeoServer Store Name Fix

### Problem
- Store name = layer_id (UUID like "550e8400...")
- GeoServer layer name = "workspace:uuid"
- Not user-friendly
- Mismatch with database code field

### Solution
- Store name = code (slug from filename)
- GeoServer layer name = "workspace:code"
- Consistent with Layer.code field
- Rename .shp files in zip to match

### Implementation

**File:** `app/infrastructure/services/geoserver_service.py`

**Method signature change:**
```python
def _to_zip(self, path: str, rename_to: str = None) -> str:
    """Rename .shp, .dbf, .shx, .prj files to match store_name."""
```

**Rename logic:**
```python
if rename_to and ext in {'.shp', '.dbf', '.shx', '.prj'}:
    new_name = f"{rename_to}{ext}"
    zf.write(f, new_name)  # renamed in zip
```

**Publish flow:**
```python
# Generate unique code (slug, no extension)
code = await generate_unique_code(base_code, layer_repo.code_exists)

# Pass to GeoServer with filename rename
result = svc.publish_shp(session.final_path, code)

# Layer.code = same code (consistent)
layer.code = code
```

**Result:**
- GeoServer layer_name = "tileserver:pt-rifijaya-sejati"
- Layer.code = "pt-rifijaya-sejati"
- file_metadata.layers = "tileserver:pt-rifijaya-sejati"

---

## 4. WMS GetFeatureInfo Support

### Problem
- Query features endpoint only handled local vector/raster files
- WMS layers couldn't return feature data on click
- No WFS, WMTS support

### Solution
- Proxy WMS GetFeatureInfo requests
- Support WMS 1.1.1 & 1.3.0
- Centralize in QueryLayerFeaturesUseCase

### Implementation

**Method:** `QueryLayerFeaturesUseCase._query_wms()`

**WMS GetFeatureInfo request:**
```python
params = {
    'service': 'WMS',
    'version': '1.3.0',
    'request': 'GetFeatureInfo',
    'info_format': 'application/json',
    'layers': layer_name,
    'query_layers': layer_name,
    'crs': 'EPSG:4326',
    'bbox': f"{lon-1},{lat-1},{lon+1},{lat+1}",
    'i': 256, 'j': 256,
    'width': 512, 'height': 512
}
```

**Layer name detection:**
1. Try: `file_metadata.geoserver.layer_name`
2. Try: `file_metadata.layers`
3. Try: URL params `layers` or `LAYERS`

**Response handling:**
```python
data = response.json()
if 'features' in data and data['features']:
    features = [f['properties'] for f in data['features']]
    return FeatureQueryResponse(type='vector', count=len(features), features=features)
```

**Version support:**
- WMS 1.3.0: `crs`, `i`, `j` params
- WMS 1.1.1: `srs`, `x`, `y` params

---

## 5. QueryLayerFeaturesUseCase Refactoring

### Problem
- Query logic scattered in endpoint
- Inline handlers for vector, raster, WMS
- Difficult to add new layer types
- Not reusable

### Solution
- Centralized usecase class
- Dispatch by layer type
- Single entry point
- Easy to extend

### Implementation

**File:** `app/usecases/getinfo_layer.py`

**Public method:**
```python
async def execute(self, layer_id: str, lon: float, lat: float) -> FeatureQueryResponse
```

**Dispatch logic:**
```python
if layer.file_type == 'external':
    if layer.layer_type == 'wms':
        return await asyncio.to_thread(self._query_wms, layer, lon, lat)
    elif layer.layer_type == 'wfs':
        return await asyncio.to_thread(self._query_wfs, layer, lon, lat)
elif layer.file_type == 'vector':
    return await asyncio.to_thread(self._query_vector, layer, lon, lat)
elif layer.file_type == 'raster':
    return await asyncio.to_thread(self._query_raster, layer, lon, lat)
```

**Handlers:**
- `_query_vector()` - GeoPandas (local vector)
- `_query_raster()` - Rasterio (local raster)
- `_query_wms()` - WMS GetFeatureInfo (remote)
- `_query_wfs()` - WFS GetFeature (remote)

**Endpoint simplification:**
```python
@router.get("/{layer_id}/features", response_model=FeatureQueryResponse)
async def query_features(layer_id: str, lon: float, lat: float, ...):
    usecase = QueryLayerFeaturesUseCase(layer_repo, session_repo)
    return await usecase.execute(layer_id, lon, lat)
```

---

## Migration Checklist

- [x] Add `cancelled` to JobStatus enum
- [x] Create migration `0003_add_celery_task_id_to_upload_sessions.py`
- [x] Update UploadSessionRepository (add `set_task_id()`)
- [x] Update trigger_tiling endpoint (capture task ID)
- [x] Add cancel endpoint (`POST /uploads/{id}/cancel`)
- [x] Update worker (cooperative cancel check)
- [x] Add utilities (generate_unique_code functions)
- [x] Update all layer creation paths (external, geoserver, tiling)
- [x] Refactor GeoServerService (rename files in zip)
- [x] Create QueryLayerFeaturesUseCase
- [x] Add WMS/WFS query handlers
- [x] Update query_features endpoint

---

## Files Changed

**Backend:**
- `app/domain/models.py` — added JobStatus.cancelled, UploadSession.celery_task_id
- `app/core/utils.py` — added generate_unique_code(async/sync)
- `app/infrastructure/db/repository.py` — added code_exists, set_task_id methods
- `app/api/v1/endpoints/upload.py` — cancel endpoint, code generation, GeoServer fix
- `app/api/v1/endpoints/layers.py` — code generation, simplified query endpoint
- `app/workers/tasks.py` — cooperative cancel check, code generation
- `app/infrastructure/services/geoserver_service.py` — rename files in zip
- `app/usecases/getinfo_layer.py` — NEW, centralized query logic

**Database:**
- `alembic/versions/0003_add_celery_task_id_to_upload_sessions.py` — NEW

**Documentation:**
- `docs/README.md` — added Recent Implementation section
- `docs/FEATURE_QUERY.md` — NEW, detailed feature query docs
- `docs/RECENT_UPDATES.md` — NEW, this file

---

## 5. WMS GetFeatureInfo Fix

**Problem:** klik layer WMS tidak mengembalikan feature.

**Dua bug di `_query_wms()` (`app/usecases/getinfo_layer.py`):**
1. BBOX `±1°` → 512px window dengan ~434 m/pixel → fitur kecil sub-pixel, tidak pernah match.
   Fix: `±0.005°` (~2 m/pixel).
2. WMS 1.3.0 + EPSG:4326 wajib bbox **lat,lon** (axis order per spec); kode kirim lon,lat
   → response selalu kosong. Fix: 1.3.0 pakai lat,lon, 1.1.1 tetap lon,lat.

---

## 6. Layer Fields untuk WMS + Refactor ke UseCase

**`GetLayerFieldsUseCase`** (`app/usecases/get_layer_fields.py`, NEW) — logika
`GET /layers/{id}/fields` pindah dari endpoint:
- vector lokal → kolom file (geopandas); raster → `band_1..band_N`
- external WMS → source lokal kalau ada (publish flow), fallback remote
  **WFS DescribeFeatureType** (`outputFormat=application/json`, kolom `gml:*` dibuang)
- external lain → `LayerFieldsUnavailableError` (404)

**Exceptions baru** (`app/core/exceptions.py`): `LayerNotFoundError`,
`LayerFieldsUnavailableError`. Endpoint tinggal map exception → HTTP 404.

Frontend: tombol Field Settings kini muncul untuk layer WMS
(`detail-view.tsx`: `file_type === 'vector' || layer_type === 'wms'`).

---

## 7. GeoServer Publish — BBox Recalculate

**Problem:** publish kadang menghasilkan bbox kosong → layer tidak muncul di peta.

**`GeoServerService._recalculate_bbox()`** (NEW) — dipanggil setelah
`create_shp_datastore`:
1. `PUT featuretypes/{store}.json?recalculate=nativebbox,latlonbbox`
2. `GET` featuretype → `latLonBoundingBox` → return `[west, south, east, north]`
3. Gagal → log warning, publish tetap lanjut

**Endpoint publish** (`upload.py`): `bbox = extract_bbox_from_file(...) or result["bbox"]`
— bbox DB tidak pernah kosong selama salah satu sumber berhasil. BBox juga tersimpan
di `file_metadata.geoserver.bbox`.

---

## 8. Catatan MVT — Properti Null

Spec Mapbox Vector Tile tidak punya tipe null → `mapbox_vector_tile.encode`
men-drop properti bernilai `None` per feature. Akibat: klik feature MVT
(props dibaca dari tile oleh deck.gl) hanya menampilkan field non-null.
`GET /layers/{id}/fields` tetap mengembalikan schema lengkap dari file sumber —
ini benar, bukan bug.

---

## 9. GeoFence (GeoNode GeoServer)

GeoServer build GeoNode aktif GeoFence dengan 0 rule → default DENY semua OWS
anonim: GetCapabilities kosong, GetMap `LayerNotDefined` (meski layer ada via REST).
`security/layers.properties` di-ignore saat GeoFence aktif.

Rule terpasang (id 1): `ALLOW service=WMS` untuk semua user — GetMap +
GetFeatureInfo anonim jalan. WFS DescribeFeatureType tidak terblokir.
Hapus: `DELETE /geoserver/rest/geofence/rules/id/1`.

Catatan URL: daftarkan WMS dengan endpoint penuh (`.../geoserver/{workspace}/wms`),
bukan root `.../geoserver` (root = redirect ke web UI, bukan WMS endpoint).

---

## Files Changed (sesi 2026-06-10, lanjutan)

**Backend (tileserver_api):**
- `app/usecases/getinfo_layer.py` — WMS GetFeatureInfo: bbox ±0.005°, axis order 1.3.0
- `app/usecases/get_layer_fields.py` — NEW, GetLayerFieldsUseCase
- `app/core/exceptions.py` — LayerNotFoundError, LayerFieldsUnavailableError
- `app/api/v1/endpoints/layers.py` — fields endpoint → usecase, cleanup imports
- `app/infrastructure/services/geoserver_service.py` — _recalculate_bbox()
- `app/api/v1/endpoints/upload.py` — bbox fallback dari GeoServer recalculate

**Frontend (dashboard):**
- `features/geo/tile/components/file-metadata-panel.tsx` — metadata editable per-key
  (kecuali `fields`/`renderMode`/`custom` — milik Field Settings)
- `features/geo/tile/detail-view.tsx` — Field Settings untuk WMS, layerId ke metadata panel

---

Last updated: 2026-06-10
