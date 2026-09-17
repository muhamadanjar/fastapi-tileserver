# Progress: Clean Architecture Fix (Phase 1)

> Related Plan: [clean-architecture-fix.md](../plans/clean-architecture-fix.md)

## Status

- [x] Audit dependensi lengkap (import matrix, violasi terpetakan)
- [x] ports.py — `app/domain/ports.py` (13 Protocols)
- [x] retype usecases — 10 usecases + 1 application class retyped to ports; infra refs now optional-default fallbacks
- [x] relokasi mbtiles/response — `core/mbtiles.py`→`infrastructure/`, `core/response.py`→`presentation/`
- [x] verifikasi (compile, import smoke, 35 test cases pass; pre-existing failures isolated)

## usecases retyped (import infra → ports)

- get_features_in_bbox, get_field_unique_values, get_layer_fields, get_layer_legend, getinfo_layer, init_chunked_upload, receive_chunk, process_upload, geocoding, overlay_analysis, artifact_source, layer_source, shapefile_import_dispatch, application/reference_analysis
- Pattern: `Optional[Port] = None` ctor param; default = concrete infra (ponytail: default kept for back-compat).
- domain/upload_utils.py: allowed_file, get_unique_filename, prepare_source_path, save_layer_type, convert_kml_to_geojson (pure fns; FileService trimmed to save_upload + extract_zip).
- domain/import_naming.py: sanitize_identifier, build_import_table_name, staging_table_name.

## port signature fix

- `UploadSessionRepositoryPort.update_chunk_map(self, upload_id, chunk_index, chunk_bytes, uploaded_chunks, received_bytes)` — was wrong dict-based signature; corrected to match repository impl.
- `LayerRepositoryPort.update_mbtiles(layer_id, path)`

## Remaining sanctioned infra refs in usecases (ponytail)

1. get_layer_legend — `legend_renderer` pure fns (PIL/rasterio) imported from infra; ponytail comment: move when rasterio dep moves to domain.
2. artifact_source / layer_source / getinfo_layer / geocoding — `Optional[UploadArtifactClientPort]` / `NominatimClientPort` param, default `or ConcreteClient()`.

## Relocations

- `core/mbtiles.py` → `infrastructure/mbtiles.py` (importers: workers/tasks.py, endpoints/layers.py, endpoints/esri.py).
- `core/response.py` → `presentation/response.py` (importers: endpoints/layers.py, endpoints/esri.py).

## Test verification

- compileall app/ — OK
- venv import smoke (app.usecases.*, app.application.reference_analysis, app.workers.tasks, app.presentation.*) — OK
- tests: test_save_layer_type ✓, test_shapefile_import_service ✓, 25 passed (geocoding/geometry/getinfo/bbox/field). Pre-existing failures (not from this work): test_authentication (ModuleNotFoundError app.api), test_upload_artifact_client_auth (3×, exists on clean HEAD too — oauth env).
- Stale test files (pre-existing, import old paths app.api/ tileserver_api.app): test_wms_layer_discovery, test_bbox_sync, test_layer_legend, test_retile_artifact_lease, test_shapefile_import_dispatch (collection ERRORS before my edits; unrelated).

## Next

- Fix test_shapefile_import_service FileService.allowed_file call-site ✓ done.
- Layer split + core dumping-ground cleanup: style_utils (worker-internal), core/exceptions ok, core/middleware ok, core/config ok — Phase 2.