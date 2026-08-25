# ESRI Download — Migrasi dari rest_service_downloader

## Goal
Ambil semua core function download Esri (MapServer/FeatureServer/ImageServer) dari `~/Documents/rest_service_downloader` dan integrasikan ke `tileserver_api`. Proses berat (download, export, discovery) tetap jalan di Celery worker.

---

## Gap Analysis

| Fitur | rest_service_downloader | tileserver_api | Status |
|---|---|---|---|
| ArcGIS REST client | Full: proxy, token, SSL ignore, POST fallback, GeoJSON↔EsriJSON, recursive split | Basic: simple GET, no fallback | ❌ Gap |
| Query strategies | ObjectID + Pagination + adaptive page split | ObjectID only | ⚠️ Partial |
| Resume cache | Disk-based resume cache per chunk | ❌ Tidak ada | ❌ Gap |
| Export formats | GeoJSON, Shapefile, GeoPackage, FileGDB, KMZ, ArcGIS Layer File | GeoJSON, Shapefile | ❌ Gap |
| Multi-layer GDB | ✅ Shared FileGDB | ❌ | ❌ Gap |
| Render-only MapServer | ✅ Image export + world file | ❌ | ❌ Gap |
| Service discovery | REST catalog scan, Portal sharing, smart discovery | ❌ | ❌ Gap |
| Download estimate | Feature count + chunk estimate | ❌ | ❌ Gap |
| Diagnostics | Error explainer, diagnostics report | ❌ | ❌ Gap |
| Celery integration | UI-driven (desktop app) | ✅ Sudah ada | ✅ OK |
| Progress tracking | ✅ | ✅ (sudah ada) | ✅ OK |

---

## Phase 1: Enhanced ArcGISClient + HTTP Utils

**Files baru/ubah:**
- `app/infrastructure/services/esri_http_utils.py` — retry session, timeout tuple, SSL control
- `app/infrastructure/services/esri_client.py` — port `arcgis_client.py` (disederhanakan)
- `app/core/utils.py` — tambah `timeout_tuple` jika belum ada

**Core functions yang dipindahkan:**
1. `create_retry_session()` — session dengan retry adapter
2. `build_final_url()` — proxy + token URL builder
3. `get_json()` — JSON request dengan error normalization
4. `get_geojson()` — native GeoJSON → EsriJSON fallback chain
5. `_post_json_raw()` — POST fallback untuk URL > 1800 chars
6. `_esri_geometry_to_geojson()` — konversi geometry Esri → GeoJSON
7. `_esri_json_to_geojson()` — konversi feature set Esri → GeoJSON
8. `get_layers_from_mapserver()` — layer listing dengan fallback probing (/layers endpoint, probe numeric)
9. `is_render_only_mapserver()` — deteksi render-only services
10. `build_render_only_layer()` — pseudo-layer untuk image export
11. `infer_geometry_type()` — infer dari metadata + renderer + sample feature
12. `can_query_layer()` — probe query capability
13. `get_feature_count()` — count query
14. `get_object_ids()` — returnIdsOnly query
15. `fetch_features_adaptive()` — ObjectID fetch dengan recursive split on partial response
16. `fetch_features_page()` — pagination fetch dengan resultOffset

**Ponytail simplifications:**
- Hapus UI-related stuff (cancel_checker → pakai Celery revoke)
- Hapus proxy/token support kalau tidak dibutuhkan → simpan sederhana, tambah nanti kalau perlu
- Hapus `DownloadSessionLog`, `DownloadDiagnostics` → ganti dengan print logging Celery
- SSL ignore → env var `ESRI_IGNORE_SSL`

---

## Phase 2: Enhanced Downloader (Celery-native)

**Files baru/ubah:**
- `app/infrastructure/services/esri_downloader.py` — rewrite total dari `downloader.py`

**Core functions yang dipindahkan:**
1. `download_by_object_ids()` — dengan ThreadPoolExecutor + resume cache
2. `download_by_pagination()` — dengan adaptive page split
3. `download_job()` — orchestrator: fetch → export (multi-format)
4. `download_map_image_job()` — image export untuk render-only MapServer
5. `_fetch_objectid_chunk_with_resume()` — resume cache read/write
6. `_fetch_page_with_resume()` — resume cache untuk pagination

**Resume cache (disederhanakan):**
- File: `app/infrastructure/services/esri_resume_cache.py`
- Simpan chunk features sebagai JSON di `data/esri_cache/{layer_id}/`
- Key: `{service_url_hash}_{layer_id}_{mode}_{chunk_key}`
- Invalidasi: beda service_url atau geometry_type → cache miss

**Ponytail simplifications:**
- Hapus `pause_event` (tidak relevan di Celery)
- Hapus `DownloadCancelled` → pakai `layer.file_metadata.download_process.status == "cancelled"`
- Max workers → dari env var `ESRI_MAX_WORKERS` (default 4)
- Hapus diagnostics report writing → log ke Celery stdout saja

---

## Phase 3: Exporters Baru

**Files baru:**
- `app/infrastructure/services/esri_exporters.py` — semua exporter dalam 1 file

**Exporters yang ditambahkan:**
1. **GeoPackage** — sudah ada logic di rest_service_downloader, port langsung
2. **KMZ/KML** — styling support dari renderer metadata
3. **File Geodatabase** (optional, low priority) — butuh `arcgisscripting` atau `geopandas` + `ogr`

**Yang sudah ada di tileserver (jangan disentuh):**
- GeoJSON export → `_write_geojson()` sudah ada
- Shapefile export → `_write_shapefile_zip()` sudah ada

**Ponytail simplifications:**
- Jangan pisah per-file mixin → 1 file `esri_exporters.py` sudah cukup
- Hapus `save_style_json`, `save_export_log` → tidak perlu untuk server API
- FileGDB → skip dulu, tambah `ponytail:` comment kalau perlu nanti

---

## Phase 4: Service Discovery Endpoint

**Files baru/ubah:**
- `app/api/v1/endpoints/esri_discovery.py` — endpoint baru
- `app/infrastructure/services/esri_service_discovery.py` — service logic

**Endpoints:**
```
POST /api/v1/esri/discover     — scan URL, detect service type, list layers
GET  /api/v1/esri/{layer_id}/info  — get layer metadata (geometry, fields, count estimate)
```

**Core functions yang dipindahkan:**
1. `detect_service_type()` — dari `service_detector.py`
2. `enrich_service_record()` — dari `catalog_intelligence.py`
3. `build_discovery_plan()` — dari `smart_discovery.py`
4. Service URL validation & normalization

**Ponytail simplifications:**
- Hapus `ServiceLibraryManager` (UI-driven catalog) → tidak relevan untuk API
- Hapus `PortalLibrary` → tidak dibutuhkan
- Discovery = 1 endpoint yang terima URL, return service info + layer list

---

## Phase 5: Download Estimate & Enhanced Celery Task

**Files baru/ubah:**
- `app/infrastructure/services/esri_estimator.py` — dari `download_estimator.py`
- `app/workers/tasks.py` — tambah task baru

**New Celery tasks:**
1. `discover_esri_service_task(layer_id, url)` — discovery async
2. `download_esri_layer_task(layer_id, output_formats)` — upgrade yang ada, tambah multi-format
3. `estimate_esri_download_task(layer_id)` — estimate before download

**Download estimate endpoint:**
```
POST /api/v1/layers/{layer_id}/download/estimate
GET  /api/v1/layers/{layer_id}/download/estimate/{task_id}
```

---

## Phase 6: DB Schema Extension

**Migration needed:**
- Tambah kolom `download_process` (JSON) → sudah ada di `file_metadata` ✅
- Tambah `download_formats` (JSON array) → default `["geojson", "shp"]`
- Layer types sudah ada: `esri_mapserver`, `esri_featureserver`, `esri_tileserver`, `esri_vectortileserver`, `esri_imageserver` ✅

---

## File Map — Source → Target

| Source (rest_service_downloader) | Target (tileserver_api) | Priority |
|---|---|---|
| `core/arcgis_client.py` | `app/infrastructure/services/esri_client.py` | P1 |
| `core/http_utils.py` | `app/infrastructure/services/esri_http_utils.py` | P1 |
| `core/downloader.py` | `app/infrastructure/services/esri_downloader.py` (rewrite) | P1 |
| `core/download_resume.py` | `app/infrastructure/services/esri_resume_cache.py` | P2 |
| `core/exporters/geopackage_exporter.py` | `app/infrastructure/services/esri_exporters.py` | P2 |
| `core/exporters/kmz_exporter.py` | `app/infrastructure/services/esri_exporters.py` | P2 |
| `core/service_detector.py` | `app/infrastructure/services/esri_service_discovery.py` | P3 |
| `core/catalog_intelligence.py` | (helpers inline) | P3 |
| `core/smart_discovery.py` | (helpers inline) | P3 |
| `core/download_estimator.py` | `app/infrastructure/services/esri_estimator.py` | P3 |
| `core/exceptions.py` | (inline ke `app/core/exceptions.py`) | P1 |
| `core/validation.py` | (helpers inline) | P2 |
| `core/utils.py` (clean_output_name dll) | `app/core/utils.py` | P2 |

**TIDAK dipindahkan:**
- UI code (`ui/`, `viewer/`, `controllers/`, `tools/`, `assets/`)
- `ServiceLibraryManager` / `PortalLibrary` (UI catalog management)
- `BookmarkManager`, `HistoryManager`, `WorkspaceManager`
- `QueueManager` (Celery sudah handle ini)
- `CrashReporter`, `HealthChecker`
- `config/app_config.py` (sudah ada `app/core/config.py`)

---

## Dependency Changes

**requirements.txt additions:**
- `pyshp` (Shapefile writer — sudah ada via geopandas)
- `sqlite3` (GeoPackage export — stdlib, no install)
- `lxml` (KMZ/KML export — optional)

**Tidak perlu tambahan** jika hanya GeoPackage + KMZ.

---

## Implementation Order

1. **Phase 1** → `esri_http_utils.py` + `esri_client.py` + exceptions
2. **Phase 2** → Rewrite `esri_downloader.py` (ObjectID + pagination + resume cache)
3. **Phase 3** → Tambah GeoPackage + KMZ exporters ke `esri_exporters.py`
4. **Phase 4** → Discovery endpoint + task
5. **Phase 5** → Estimate endpoint + enhance download task (multi-format, image export)
6. **Phase 6** → Migration jika perlu (kemungkinan tidak perlu)

Setiap phase bisa di-test independen. Phase 1-2 adalah yang paling bernilai.
