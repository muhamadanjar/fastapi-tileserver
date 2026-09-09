# Progress: Vector Overlay Analysis

Related Plan: [vector-overlay-analysis](../plans/vector-overlay-analysis.md)

## Status: Complete (Phase 1 + Phase 2)

## Phase 1 Tasks

- [x] 1. Domain layer — Add `OverlayOperation` enum, `AnalysisResult` model
- [x] 2. Schemas — Add request/response models for analysis API
- [x] 3. Geometry compatibility module — rules for operation + geometry type matching
- [x] 4. Overlay operations core — intersection, union, dissolve, clip, difference, buffer
- [x] 5. Analysis service — orchestration: load layers, validate, run, save result
- [x] 6. API endpoints — analysis router with all 7 endpoints
- [x] 7. Layer source adapters — load from layers table + project features + upload
- [x] 8. Error handling — edge cases: empty result, self-operation, null geometry, mixed types
- [x] 9. Download/export — GeoJSON + Shapefile export for result
- [x] 10. Integration test — end-to-end analysis flow (tests/test_overlay_operations.py, 10 tests)

## Phase 2 Tasks

- [x] 11. Project features (survey) as analysis input — load features table as GeoDataFrame
- [x] 12. New operations — sym_difference, simplify, spatial_join, centroid (+ geometry compat + tests)
- [x] 13. Async execution — Celery task for >=100k features, status polling endpoint
- [x] 14. TTL cleanup — purge abandoned ephemeral layers older than TTL
- [x] 15. Update feature docs + plan status