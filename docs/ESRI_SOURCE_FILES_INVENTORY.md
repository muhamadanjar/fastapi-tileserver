# Rest Service Downloader — Core File Inventory

Sumber: `~/Documents/rest_service_downloader`
Target: `~/Development/base-project-apps/services/tileserver_api`

## Kategori File

### ✅ SUDAH DI-MIGRATE (Phase 1–5)

| Source File | Target File | Status | Fungsi |
|---|---|---|---|
| `core/arcgis_client.py` | `app/infrastructure/services/esri_client.py` | ✅ Done | ArcGIS REST client: JSON requests, GeoJSON↔EsriJSON, POST fallback, layer probing, geometry inference, render-only detection, feature fetch (ObjectID + pagination + recursive split) |
| `core/http_utils.py` | `app/infrastructure/services/esri_http_utils.py` | ✅ Done | HTTP session: retry adapter, timeout tuple, SSL warning control |
| `core/downloader.py` | `app/infrastructure/services/esri_downloader.py` | ✅ Rewrite | Orchestrator download: ObjectID mode, pagination fallback, multi-format export, image export for render-only |
| `core/download_resume.py` | `app/infrastructure/services/esri_resume_cache.py` | ✅ Done | Disk-based resume cache per chunk dengan service_url + geometry_type validation |
| `core/exporters/geopackage_exporter.py` | _(inline di `esri_downloader.py`)_ | ✅ Done | GeoPackage export via geopandas (proper WKB) |
| `core/exporters/kmz_exporter.py` | _(inline di `esri_downloader.py`)_ | ✅ Done | KMZ export: GeoJSON → KML → zip |
| `core/download_estimator.py` | `app/infrastructure/services/esri_estimator.py` | ✅ Done | Estimate feature count, chunk count, confidence |
| `core/service_detector.py` | _(logic inline di `esri_client.py` + `esri.py`)_ | ✅ Done | Detect service type dari URL path |
| `core/exceptions.py` (bagian) | `app/core/exceptions.py` | ✅ Done | `EsriDownloadError`, `DownloadCancelled`, `ServiceConnectionError` |
| `config/app_config.py` (env vars) | `app/core/config.py` | ✅ Done | ESRI_MAX_WORKERS, ESRI_IGNORE_SSL, ESRI_RESUME_CACHE_DIR, timeouts |

---

### 🟡 BELUM DI-MIGRATE — BISA DIAMBIL (Core Logic)

| Source File | Ukuran | Rekomendasi | Fungsi |
|---|---|---|---|
| `core/utils.py` | ~50 lines | ⭐ Ambil — helper penting | `slugify`, `clean_output_name`, `normalized_output_name`, `ensure_folder`, `create_prj` (file .prj untuk Shapefile) |
| `core/validation.py` | ~120 lines | ⭐ Ambil — validation layer | `validate_arcgis_url`, `validate_proxy_url`, `validate_output_directory`, `validate_worker_count`, `validate_service_json` |
| `core/sanitize.py` | ~80 lines | Ambil — security | Sanitasi token/password dari URL dan data structure (redaksi credentials) |
| `core/export_formats.py` | ~40 lines | ⭐ Ambil — format normalization | `normalize_output_format()`, `normalize_output_formats()` — mapping alias ke canonical format name |
| `core/service_library_constants.py` | ~60 lines | Ambil — konstanta | Konstanta untuk ArcGIS: `SERVICE_TYPES`, `SUPPORTED_DOWNLOAD_TYPES`, dll |
| `core/catalog_intelligence.py` | ~100 lines | Ambil — metadata enrichment | `build_catalog_metadata()`, `service_path_from_url()`, `catalog_root_from_service_url()` |
| `core/smart_discovery.py` | ~75 lines | Ambil — discovery planning | `DiscoveryPlan`, `infer_arcgis_rest_root()`, `looks_like_portal_sharing_url()`, `build_discovery_plan()` |
| `core/schema_utils.py` | ~100 lines | Skip — terlalu spesifik untuk desktop | JSON envelope/versioning untuk file lokal (bookmarks, catalog, workspace) |
| `core/error_explainer.py` | ~80 lines | Ambil — error classification | `explain_exception()` → classify error dan beri saran user-facing |
| `core/error_handling.py` | ~50 lines | Ambil — error logging | `log_exception()` dengan context-aware level selection |
| `core/logging_utils.py` | ~60 lines | Ambil — logging setup | Logger factory, log rotation, security warning logging |
| `core/exceptions.py` (sisa) | ~40 lines | Ambil — lebih banyak exceptions | `DownloadCancelled`, `InvalidOutputFormat`, `NoFeaturesReturned`, `QueryNotSupported`, `RestServiceDownloaderError` |
| `core/download_session.py` | ~60 lines | Skip — UI logging | Session logging untuk desktop app (JSONL per-run) |
| `core/job_model.py` | ~40 lines | Ambil — data model | `DownloadJob` dataclass — bisa jadi basis untuk layer download metadata |
| `core/download_diagnostics.py` | ~80 lines | Skip — UI diagnostics | Diagnostics report writing untuk desktop UI |
| `core/cache_manager.py` | ~40 lines | Ambil — cache cleanup | Maintenance: hapus cache lama (resume cache, discovery cache, temp) |
| `core/import_manager.py` | ~50 lines | Ambil — bulk import | `BulkUrlImportManager` — import URL dari CSV/TXT (bisa jadi endpoint bulk add) |
| `core/queue_manager.py` | ~60 lines | Skip — diganti Celery | Desktop queue management — Celery sudah handle ini |
| `core/workspace_manager.py` | ~100 lines | Ambil — workspace presets | Daftar catalog default (BIG, Jakarta Satu, dll) — bisa jadi seed data |
| `core/bookmark_manager.py` | ~80 lines | Ambil — bookmark CRUD | Simpan/load bookmark service URL (bisa jadi endpoint save Esri service) |
| `core/history_manager.py` | ~80 lines | Ambil — download history | Riwayat download (bisa jadi endpoint history) |
| `services/service_discovery_cache.py` | ~60 lines | Ambil — cache adapter | Cache TTL untuk discovery results (bisa pakai Redis) |
| `core/security/token_store.py` | ~80 lines | Ambil — token management | Secure token storage untuk ArcGIS auth (bisa jadi env var / DB field) |
| `core/exporters/base_exporter.py` | ~180 lines | Skip — UI-oriented | Exporter facade dengan style JSON saving, export log — tidak relevan untuk server |
| `core/exporters/geojson_exporter.py` | ~40 lines | Skip — sudah ada | GeoJSON export sudah ada di tileserver |
| `core/exporters/shapefile_exporter.py` | ~60 lines | Skip — sudah ada | Shapefile export sudah ada di tileserver |
| `core/exporters/geopackage_exporter.py` | ~120 lines | ✅ Sudah migrate | GeoPackage export via sqlite3 — kita pakai geopandas yang lebih proper |
| `core/exporters/file_geodatabase_exporter.py` | ~200 lines | ⚠️ Optional | FileGDB export — butuh `arcgisscripting` atau GDAL/OGR |
| `core/exporters/exporter_manager.py` | ~60 lines | Ambil — export orchestration | Multi-format export dispatcher (bisa inspire `EsriDownloader._export_and_save`) |
| `core/exporters/kmz_exporter.py` | ~100 lines | ✅ Sudah migrate | KMZ export sudah di-migrate ke `esri_downloader.py` |
| `core/runtime_check.py` | ~40 lines | Skip — desktop only | Runtime check untuk PyInstaller bundle |
| `core/update_checker.py` | ~60 lines | Skip — desktop only | App update checker untuk desktop |
| `core/crash_reporter.py` | ~80 lines | Skip — desktop only | Crash reporting untuk desktop app |
| `core/health_checker.py` | ~60 lines | Ambil — service health | Check Esri service health/latency (bisa jadi endpoint health check) |
| `core/service_library.py` | ~500 lines | Ambil sebagian | ServiceLibraryManager — catalog management. Ambil logic discovery + enrichment, skip UI parts |
| `core/portal_library.py` | ~300 lines | ⚠️ Optional | Portal Sharing library — OAuth + Portal REST. Kompleks, skip dulu |
| `core/service_library_index.py` | ~100 lines | Ambil — index helpers | URL indexing, deduplication, normalization untuk catalog |
| `core/service_library_metadata.py` | ~200 lines | Ambil sebagian | Metadata inference: province, region, catalog name dari URL |
| `core/service_library_defaults.py` | ~60 lines | Ambil — default catalog | Default service catalog (Gistaru, BIG, dll) — seed data |

---

### ❌ SKIP — TIDAK RELEVAN (Desktop / UI Only)

| Source File | Alasan Skip |
|---|---|
| `app.py` | Entry point desktop app (Gradio/CustomTkinter) |
| `config/app_config.py` (sebagian besar) | Path desktop, app version, UI settings |
| `ui/*` | Seluruh UI code |
| `viewer/*` | Data viewer desktop |
| `controllers/*` | UI controllers |
| `tools/*` | Development tools |
| `assets/*` | UI assets |
| `tests/*` | Desktop app tests |
| `core/download_session.py` | Session logging untuk desktop UI |
| `core/download_diagnostics.py` | Diagnostics report untuk desktop |
| `core/queue_manager.py` | Desktop queue — Celery sudah handle |
| `core/crash_reporter.py` | Desktop crash reporting |
| `core/update_checker.py` | Desktop app update checker |
| `core/runtime_check.py` | PyInstaller runtime check |
| `core/schema_utils.py` | Desktop JSON versioning |
| `core/security/token_store.py` | Desktop secure token storage (OS keychain) |

---

## Prioritas Migrasi Berikutnya

### P1 — High Value (langsung usable)

1. **`core/utils.py`** → `app/core/utils.py`
   - `normalized_output_name()` — generate nama file yang konsisten dari layer name + geometry type
   - `create_prj()` — buat file `.prj` untuk Shapefile (EPSG:4326 WGS84)
   - `clean_output_name()` — sanitasi nama file dari karakter aneh

2. **`core/validation.py`** → `app/infrastructure/services/esri_validation.py`
   - `validate_arcgis_url()` — validasi URL Esri (scheme, path, service type)
   - `validate_service_json()` — validasi response JSON dari Esri server
   - `validate_output_directory()` — validasi + create output directory
   - `validate_worker_count()` — validasi max workers (1–16)

3. **`core/export_formats.py`** → `app/core/utils.py` (append)
   - `normalize_output_format()` / `normalize_output_formats()` — mapping alias ke canonical name

4. **`core/service_library_constants.py`** → `app/infrastructure/services/esri_constants.py`
   - `SERVICE_TYPES`, `SUPPORTED_DOWNLOAD_TYPES`, konstanta ArcGIS

5. **`core/smart_discovery.py`** → `app/infrastructure/services/esri_discovery.py`
   - `DiscoveryPlan`, `build_discovery_plan()` — infer REST root dari URL apapun
   - `infer_arcgis_rest_root()` — ekstrak `/rest/services` dari URL service

6. **`core/catalog_intelligence.py`** → `app/infrastructure/services/esri_metadata.py`
   - `build_catalog_metadata()` — enrich service record dengan host, path, folder info
   - `service_path_from_url()` — ekstrak service path dari URL

### P2 — Medium Value (nice to have)

7. **`core/sanitize.py`** → `app/core/utils.py` (append)
   - `sanitize_data()` / `sanitize_text()` — redact tokens dari URL dan dict
   - Berguna untuk logging tanpa leak credentials

8. **`core/error_explainer.py`** → `app/infrastructure/services/esri_errors.py`
   - `explain_exception()` → classify error dan beri user-friendly message

9. **`core/error_handling.py`** → `app/infrastructure/services/esri_errors.py` (append)
   - `log_exception()` — context-aware error logging

10. **`core/logging_utils.py`** → skip (Python stdlib `logging` sudah cukup)

11. **`core/cache_manager.py`** → `app/infrastructure/services/esri_cache_manager.py`
    - Cleanup expired resume cache + discovery cache

12. **`core/import_manager.py`** → `app/infrastructure/services/esri_bulk_import.py`
    - Import URL list dari CSV/TXT → bulk add layer

### P3 — Low Value (opsional, bisa di-skip)

13. **`core/workspace_manager.py`** → seed data untuk default catalog
14. **`core/bookmark_manager.py`** → endpoint save Esri service
15. **`core/history_manager.py`** → endpoint download history
16. **`services/service_discovery_cache.py`** → cache layer untuk discovery
17. **`core/service_library_metadata.py`** → metadata inference (province, region)
18. **`core/service_library_defaults.py`** → default seed catalog
19. **`core/service_library_index.py`** → URL dedup + normalization
20. **`core/exporters/exporter_manager.py`** → export dispatcher inspiration
21. **`core/health_checker.py`** → service health check endpoint
22. **`core/service_library.py`** → ambil bagian discovery, skip catalog CRUD
23. **`core/exporters/file_geodatabase_exporter.py`** → FileGDB (butuh GDAL/OGR)
24. **`core/portal_library.py`** → Portal Sharing (kompleks, butuh OAuth)

---

## Summary

| Kategori | Jumlah Files | Status |
|---|---|---|
| Sudah di-migrate | 9 | ✅ Done |
| Bisa diambil (P1) | 6 | ⭐ Mulai dari sini |
| Bisa diambil (P2) | 5 | Medium priority |
| Bisa diambil (P3) | 12 | Low priority / optional |
| Skip (desktop-only) | 15+ | ❌ Tidak relevan |

**Total core files yang bisa di-migrate: ~23 files**
**Yang sudah selesai: 9 files**
**Sisa yang bisa diambil: ~14 files (P1 + P2)**
