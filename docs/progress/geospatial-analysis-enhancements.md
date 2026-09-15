Related Plan: [Geospatial Analysis Enhancements](../plans/geospatial-analysis-enhancements.md)

# Implementation Progress

Status: Backend complete (2026-09-12).
Feature guide: [Polygon intersection area metrics](../features/geospatial-analysis-enhancements.md)

## Active scope correction (2026-09-10)

The user clarified that analysis concerns two generic spatial datasets.
The flood/village decisions below are an archived example, not requirements
for the general feature. No village, flood, or facility layer is mandatory.

- [x] Correct plan scope and remove example-only terms from CONTEXT.md.
- [x] Select generic polygon intersection enhancement.
- [x] Confirm per-pair A/B source IDs, intersection area, and percentages of
  the full original A and B feature areas.
- [x] Resolve overlapping pairs, remaining input/output rules, and acceptance criteria.

- [x] Keep overlapping A–B pair results independent without automatic merging;
  do not represent summed pair areas as unique coverage.

- [x] Include only positive-area intersections; boundary-only contact produces
  no row, and no positive-area matches yields an empty result.

- [x] Provide area in square meters and hectares, percentages on a 0–100 scale,
  and round only for presentation.

- [x] Allow a selected unique, non-null source ID field or generated IDs scoped
  to one run, retaining a mapping to the source records.

- [x] Block enhanced area analysis on invalid polygons and report source IDs
  and reasons; require correction instead of silent repair or omission.

- [x] Add the enhancement as an optional setting on existing polygon–polygon
  intersection; preserve existing behavior when disabled.
- [x] Consolidate agreed rules into acceptance checks in the plan.
- [x] Confirm shared understanding of the consolidated backend scope.
- [x] Resolve technical contract details against the current implementation.
- [x] Implement and verify the enhancement after scope confirmation.
- [x] Publish final feature/API documentation.

## Verification

- Targeted regression suite: **48 passed** (`test_intersection_area.py`,
  `test_intersection_area_api.py`, `test_overlay_operations.py`).
- Covers area/percentage fixtures, independent pairs, holes/MultiPolygon,
  edge/point-only contact, tiny overlap, empty layers, differing CRS, invalid
  geometry/IDs, source snapshots, real SQLite repositories with foreign keys,
  API preflight/run/preview/download/save/discard, worker execution with a
  JSON-serialized queue payload, failure status, and legacy intersection.
- Also covers survey geometry loading, analysis result reuse, configurable
  export locations, and async polling with the public result layer ID.
- Broader suite: **181 passed, 3 skipped, 3 failed**. Failures are the existing
  upload-auth header assertions in `test_upload_artifact_client_auth.py`, which
  expect no `X-Upload-Internal-Client` header. `git show HEAD` confirms the
  unchanged upload client already includes that header. Skipped tests require
  an explicitly configured test PostGIS database.
- This checkout is named `milkfish`; the legacy auth test imports
  `tileserver_api`. The broader run used a temporary import-path symlink to
  this checkout without editing repository imports.
- Compilation and `git diff --check` passed. Graphify AST index refreshed.
- No live RabbitMQ delivery, production deployment, or frontend verification
  was performed. Worker-path tests run the shared execution entry point locally.

## Integration notes

- Optional request settings, result/source files, and existing layer metadata
  provide persistence without database-field changes or migrations.
- Enhanced failed async runs retain inactive placeholders to respect foreign
  keys and expose their error status. Existing retry policy remains unchanged.
- Survey GeoJSON geometries are converted to Shapely before analysis. Completed
  analysis results can be loaded as input, and preview uses the recorded path.
- The existing status endpoint now also accepts the result layer ID returned
  by `/run`, making async polling possible directly from the public response.
- No standalone ADR was necessary: this extends the existing architecture
  without a new storage engine, service boundary, or migration commitment.

## Archived example discussion

The earlier flood/village interview was explicitly superseded by the user's
generic two-layer scope correction. Its notes remain in the plan for context;
they are not outstanding implementation tasks or constraints on this feature.
