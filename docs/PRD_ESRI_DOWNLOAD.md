# PRD: Esri Data Download — Full Feature Parity

## Problem Statement

Tileserver saat ini hanya punya fitur download Esri yang sangat dasar: bisa fetch object IDs, query per chunk, dan export ke GeoJSON + Shapefile. Fitur ini tidak mencakup kemampuan-kemampuan penting dari `rest_service_downloader` yang sudah terbukti dipakai di produksi, seperti: fallback GeoJSON→EsriJSON, recursive split pada partial response, resume cache, export ke GeoPackage/KMZ, image export untuk render-only MapServer, dan service discovery. Akibatnya, banyak layanan Esri yang gagal didownload atau hanya bisa didownload sebagian.

## Solution

Migrasi semua core function download Esri dari `rest_service_downloader` ke `tileserver_api`, diadaptasi ke arsitektur server-side dengan Celery worker. Semua proses berat (download, export, discovery) berjalan sebagai Celery task dengan progress tracking real-time.

## User Stories

1. Sebagai user geoportal, saya ingin memasukkan URL Esri MapServer/FeatureServer dan melihat daftar semua sublayer yang tersedia sebelum mendownload, sehingga saya bisa memilih layer spesifik yang saya butuhkan
2. Sebagai user geoportal, saya ingin mendownload semua sublayer dari satu layanan Esri sekaligus, sehingga saya tidak perlu mendownload satu-satu secara manual
3. Sebagai user geoportal, saya ingin memilih format output (GeoJSON, Shapefile, GeoPackage, KMZ) saat mendownload, sehingga data yang dihasilkan kompatibel dengan software GIS yang saya gunakan
4. Sebagai user geoportal, saya ingin melihat progress download secara real-time (persentase, sublayer yang sedang didownload), sehingga saya tahu estimasi waktu selesai
5. Sebagai user geoportal, saya ingin download tetap berjalan meskipun koneksi terputus sementara (resume), sehingga untuk layer besar saya tidak perlu mengulang dari awal
6. Sebagai user geoportal, saya ingin download Esri berjalan di background tanpa memblokir UI, sehingga saya bisa tetap menggunakan aplikasi saat proses download berjalan
7. Sebagai user geoportal, saya ingin bisa membatalkan download yang sedang berjalan, sehingga saya bisa menghentikan download yang memakan waktu terlalu lama
8. Sebagai user geoportal, saya ingin download bekerja pada layanan Esri yang tidak mendukung GeoJSON format, menggunakan fallback Esri JSON, sehingga tidak semua layanan gagal karena format incompatibility
9. Sebagai user geoportal, saya ingin bisa mendownload layanan Esri yang hanya punya endpoint render (image-only MapServer) sebagai gambar georeferensi, sehingga layanan peta citra juga bisa didokumentasikan
10. Sebagai admin geoportal, saya ingin memperkirakan ukuran download sebelum memulai (jumlah fitur, jumlah chunk), sehingga saya bisa memutuskan apakah akan mendownload sekarang atau nanti
11. Sebagai user geoportal, saya ingin hasil download tersedia sebagai file yang bisa diakses via HTTP endpoint, sehingga saya bisa mendownload hasil ke mesin lokal
12. Sebagai user geoportal, saya ingin layer Esri yang sudah didownload otomatis mencatat manifest (jumlah fitur per sublayer, format output, waktu selesai), sehingga saya bisa audit apa yang sudah didownload
13. Sebagai user geoportal, saya ingin server menangani URL yang panjang (objectIds banyak) secara otomatis dengan POST request, sehingga tidak ada error karena URL terlalu panjang
14. Sebagai user geoportal, saya ingin server mendeteksi secara otomatis ketika response server terpotong (partial response) dan retry secara recursive, sehingga download selalu lengkap
15. Sebagai user geoportal, saya ingin geometry type terdeteksi otomatis dari metadata atau sample feature, sehingga saya tidak perlu menebak tipe geometri layer
16. Sebagai admin geoportal, saya ingin bisa melakukan scan URL Esri REST root untuk menemukan semua layanan yang tersedia, sehingga saya bisa menambahkan banyak layanan sekaligus

## Implementation Decisions

### Modules yang Dibuat/Dimodifikasi

**New modules:**
- `app/infrastructure/services/esri_http_utils.py` — retry session, SSL control, timeout tuple (port dari `core/http_utils.py`)
- `app/infrastructure/services/esri_client.py` — ArcGIS REST client lengkap dengan: proxy/token builder, GeoJSON↔EsriJSON conversion, POST fallback, recursive split, geometry inference, render-only detection, layer probing (port dari `core/arcgis_client.py`, disederhanakan)
- `app/infrastructure/services/esri_exporters.py` — GeoPackage dan KMZ exporters (port dari `core/exporters/`)
- `app/infrastructure/services/esri_resume_cache.py` — disk-based resume cache per chunk, key-based invalidasi (port dari `core/download_resume.py`, disederhanakan)
- `app/infrastructure/services/esri_estimator.py` — download estimate: feature count, chunk count, confidence (port dari `core/download_estimator.py`)
- `app/api/v1/endpoints/esri.py` — REST endpoints baru untuk discovery, download trigger, estimate
- `app/api/v1/endpoints/esri_downloads.py` — endpoint untuk akses file hasil download

**Modified modules:**
- `app/infrastructure/services/esri_downloader.py` — rewrite total: orchestrator download multi-strategi (ObjectID + pagination), multi-format export, image export (port dari `core/downloader.py`)
- `app/workers/tasks.py` — tambah task: `discover_esri_service_task`, `estimate_esri_download_task`, upgrade `download_esri_layer_task` dengan multi-format dan resume
- `app/domain/schemas.py` — tambah request/response schemas baru untuk Esri download
- `app/domain/models.py` — tambah `LayerType.esri_imageserver` (jika belum ada)
- `app/core/exceptions.py` — tambah `EsriDownloadError`, `DownloadCancelled`
- `app/core/config.py` — tambah env vars: `ESRI_MAX_WORKERS`, `ESRI_IGNORE_SSL`, `ESRI_RESUME_CACHE_DIR`

### Arsitektur Download

```
POST /api/v1/layers/{layer_id}/download  →  Celery: download_esri_layer_task()
                                                    ↓
                                          EsriDownloader.download_job()
                                                    ↓
                                   ┌────────────────┼────────────────┐
                                   ↓                ↓                ↓
                            download_by       download_by     download_map
                            _object_ids       _pagination      _image_job
                                   ↓                ↓                ↓
                            EsriClient          EsriClient      EsriClient
                            .fetch_features     .fetch_features .export
                            _adaptive()         _page()         /export
                                   ↓                ↓                ↓
                            esri_exporters   esri_exporters   world file
                            .geojson         .geojson         + metadata
                            .shapefile       .shapefile
                            .geopackage      .geopackage
                            .kmz             .kmz
```

### API Contracts

**Discovery:**
```
POST /api/v1/esri/discover
Body: { "url": "https://..." }
Response: { "service_type": "MapServer"|"FeatureServer",
            "layers": [{"id": 0, "name": "...", "geometry_type": "..."}],
            "render_only": false }
```

**Download Estimate:**
```
POST /api/v1/layers/{layer_id}/download/estimate
Body: { "output_formats": ["geojson", "geopackage"] }
Response: { "feature_count": 1234, "estimated_chunks": 25,
            "confidence": "medium", "notes": [...] }
```

**Download Trigger (existing, upgraded):**
```
POST /api/v1/layers/{layer_id}/download
Body: { "output_formats": ["geojson", "shapefile", "geopackage", "kmz"] }
Response: { "layer_id": "...", "task_id": "..." }
```

**Download Status (existing, upgraded):**
```
GET /api/v1/layers/{layer_id}/download/status
Response: { "status": "processing"|"done"|"failed"|"cancelled",
            "percent": 67, "current_sublayer": "Layer 3",
            "sublayers_done": 2, "sublayers_total": 5,
            "task_id": "...", "started_at": "...",
            "manifest": {...} }  ← only present when status=done
```

**Download Files (existing, upgraded):**
```
GET /api/v1/layers/{layer_id}/download/files
Response: [{ "path": "0_jalan/shp/jalan.zip", "size": "2.3 MB",
             "url": "/api/v1/esri/downloads/0_jalan/shp/jalan.zip" }]
```

**Cancel Download (existing):**
```
DELETE /api/v1/layers/{layer_id}/download
Response: { "layer_id": "...", "message": "Download cancelled" }
```

**Downloaded File Access:**
```
GET /api/v1/esri/downloads/{layer_id}/**path
→ FileResponse dari data/download/{layer_id}/
```

### Schema Changes

Tidak ada migration DB baru. Semua info download sudah tersimpan di `Layer.file_metadata.download_process` (JSON column).

Yang ditambahkan:
- `file_metadata.download_process.manifest` — manifest hasil download (sublayers, skipped, feature counts)
- `file_metadata.download_process.output_formats` — format yang dipilih saat download
- `file_metadata.download_process.estimate` — hasil estimate (opsional, disimpan jika user request estimate dulu)

### Download Strategies

Dua strategi download, otomatis fallback:
1. **ObjectID mode** (default): fetch all objectIds → query per chunk → assemble. Akurat, mendukung resume.
2. **Pagination mode** (fallback): `resultOffset` + `resultRecordCount`. Untuk server yang tidak mendukung `returnIdsOnly`. Adaptive page split jika page gagal.

### Resume Cache

- Lokasi: `data/esri_cache/` (configurable via `ESRI_RESUME_CACHE_DIR`)
- Key: `{sha256(service_url)}_{layer_id}_{mode}_{chunk_key}.json`
- Invalidasi: beda service_url atau geometry_type → cache miss → re-download
- Auto-cleanup: cache > 7 hari dihapus saat app startup

### Export Formats

| Format | Library | Notes |
|---|---|---|
| GeoJSON | stdlib `json` | Sudah ada, tidak berubah |
| Shapefile | `geopandas` | Sudah ada, tidak berubah |
| GeoPackage | stdlib `sqlite3` | Baru, dari rest_service_downloader |
| KMZ | stdlib `zipfile` + `xml.sax` | Baru, dari rest_service_downloader |
| FileGDB | — | Skip (ponytail: butuh arcgissing, tambah jika ada demand) |

### Error Handling

- `EsriDownloadError` — server error, query gagal, no features returned
- `DownloadCancelled` — user cancel via API, raise di progress callback
- Retry: ObjectID chunk retry 3× dengan exponential backoff
- POST fallback otomatis jika URL > 1800 karakter
- Partial response detection → recursive split ke chunk lebih kecil

### Celery Task Design

Semua task pakai `bind=True, max_retries=1` (download task) atau `max_retries=3` (discovery/estimate):
- `download_esri_layer_task(self, layer_id, output_formats=None)` — max_retries=1, countdown=10
- `discover_esri_service_task(self, layer_id, url)` — max_retries=3, countdown=5
- `estimate_esri_download_task(self, layer_id, output_formats=None)` — max_retries=3, countdown=5

Progress callback menulis ke `Layer.file_metadata.download_process` via `SyncLayerRepository.update_download_progress()`.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ESRI_MAX_WORKERS` | `4` | Max ThreadPoolExecutor workers per download |
| `ESRI_IGNORE_SSL` | `false` | Ignore SSL verification untuk server self-signed |
| `ESRI_RESUME_CACHE_DIR` | `data/esri_cache` | Direktori resume cache |
| `ESRI_REQUEST_TIMEOUT` | `15` | Timeout untuk metadata requests (detik) |
| `ESRI_DOWNLOAD_TIMEOUT` | `180` | Timeout untuk download requests (detik) |

### Yang TIDAK Dipindahkan (Out of Scope dari Migrasi)

Semua UI-related code dari `rest_service_downloader`:
- ServiceLibraryManager / PortalLibrary (UI catalog management)
- BookmarkManager, HistoryManager, WorkspaceManager
- QueueManager (Celery sudah handle)
- CrashReporter, HealthChecker
- DownloadSessionLog, DownloadDiagnostics (ganti dengan Celery logging)
- ErrorExplainer (ganti dengan logging)
- DownloadEstimator UI components (keep logic, drop UI)

## Testing Decisions

### Testing Approach

Hanya test external behavior (API contracts, download results), bukan implementation details internal dari `EsriClient` atau `EsriDownloader`.

### Modules yang Ditest

1. **`esri_client.py`** — Test via integration test dengan mock server:
   - `get_layers_from_mapserver()` → return layer list
   - `get_geojson()` → GeoJSON atau EsriJSON fallback
   - `fetch_features_adaptive()` → recursive split on partial response
   - `infer_geometry_type()` → correct geometry detection
   - POST fallback saat URL > 1800 chars
   - Render-only MapServer detection

2. **`esri_downloader.py`** — Test orchestrator behavior:
   - Download lengkap ObjectID mode
   - Fallback ke pagination mode
   - Multi-format export menghasilkan file yang valid
   - Resume cache: cache hit reuse, cache miss re-download

3. **`esri_exporters.py`** — Test output validity:
   - GeoPackage: file SQLite valid, tabel terisi
   - KMZ: file ZIP valid, KML well-formed

4. **API endpoints (`esri.py`)** — Test via FastAPI TestClient:
   - Discovery endpoint → correct response shape
   - Estimate endpoint → valid estimate
   - Download trigger → task queued
   - Cancel → status berubah

5. **Celery tasks** — Test via `celery_worker` fixture:
   - Task berjalan dan menulis progress ke DB
   - Cancel detection bekerja
   - Error handling dan retry

### Prior Art

- `app/workers/tasks.py` — existing `process_tiling_task` dan `download_esri_layer_task` sudah punya pattern progress callback + DB update
- `app/api/v1/endpoints/layers.py` — existing download endpoints sudah punya pattern trigger/status/cancel
- `app/infrastructure/db/repository.py` — `SyncLayerRepository.update_download_progress()` sudah ada

## Out of Scope

1. **File Geodatabase export** — butuh `arcgisscripting` atau `ogr` yang kompleks, skip sampai ada demand eksplisit
2. **Service Library / Catalog management** — UI-driven feature dari rest_service_downloader, tidak relevan untuk server API
3. **Portal Sharing authentication** — OAuth/token management untuk ArcGIS Online/Enterprise, cukup simpan token di request body jika dibutuhkan
4. **Proxy support** — rest_service_downloader punya generic proxy URL rewriting, tidak dibutuhkan di server-side context
5. **Bookmark, History, Workspace** — user-state management yang hanya relevan untuk desktop app
6. **Download estimasi dengan bandwidth prediction** — estimate saat ini hanya hitung feature count + chunk count, tidak prediksi waktu

## Further Notes

- **Ponytail principle**: Exporters disatukan dalam 1 file (`esri_exporters.py`) alih-alih mixin-per-file seperti aslinya. Lebih sedikit file, lebih mudah maintain.
- **Resume cache disederhanakan**: Aslinya pakai complex key validation dengan service_url + geometry_type matching. Di server context, cukup hash service_url sebagai key — geometry sudah fixed per layer.
- **Celery sebagai replacement untuk semua UI state management**: pause/resume/cancel yang di desktop app dihandle via threading events, di server cukup via DB flag (`download_process.status`).
- **Image export untuk render-only MapServer**: Ini fitur yang unik dari rest_service_downloader — beberapa MapServer tidak punya feature layers tapi punya `/export` endpoint. Dengan `download_mode: "image_export"`, layer ini tetap bisa didownload sebagai georeferenced image + world file.
- **Recursive split pada partial response**: Beberapa ArcGIS server return 200 OK tapi dengan feature count < requested. Downloader otomatis detect dan split chunk yang gagal menjadi sub-chunk lebih kecil, menjamin download lengkap.
- **POST fallback**: URL dengan banyak objectIds bisa melebihi limit web server/gateway. ArcGISClient otomatis switch ke POST saat encoded URL > 1800 karakter.
