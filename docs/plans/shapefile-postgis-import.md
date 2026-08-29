# Shapefile import to PostGIS

Progress: [shapefile-postgis-import](../progress/shapefile-postgis-import.md)

## Goal

Keep upload completion separate from processing. After any supported upload method finishes receiving a shapefile ZIP, the existing tiling/GeoServer process remains available and an explicit `Kirim ke PostGIS` action can enqueue a Celery import. The worker validates and imports every complete shapefile dataset in the archive into separate dynamic tables in the `geodata` PostgreSQL schema.

## Confirmed behavior

- A shapefile upload is a ZIP containing one or more matching `.shp`, `.dbf`, `.shx`, and `.prj` sets. A `.cpg` file is optional per dataset.
- Direct, chunked, and artifact-handoff uploads stage the source without automatically dispatching an import; the explicit import endpoint uses one centralized dispatcher.
- Other formats retain their existing behavior and report import status `not_applicable`.
- PostgreSQL with PostGIS is required. Geometry is validated, transformed to EPSG:4326, and stored in `geom`.
- Empty datasets, invalid/empty geometries, unknown CRS, mixed geometry families, unsafe ZIPs, and oversized datasets fail atomically.
- Final tables use `<sanitized-dataset-name>_<first-8-layer-id-characters>`, with deterministic collision suffixes. All staging tables are published only after every dataset is valid and ready.
- Each table has `id BIGSERIAL PRIMARY KEY`, sanitized native DBF columns, and `geom geometry(Geometry, 4326)` with a GiST index.
- A successful import creates or updates the allocated Layer as `postgis`, retaining source metadata for later tiling or publication.
- Import status, task identity, progress, result metadata, retry, and cancellation are independent of the existing tiling status.
- Layer deletion previews and removes the owned `geodata` table. A failed table drop aborts deletion of the Layer row.

## Safety limits

- Maximum uncompressed ZIP size: configurable, default 1 GiB.
- Maximum feature count: configurable, default 1,000,000.
- Reject path traversal, symlinks, encrypted entries, suspicious compression ratios, incomplete sidecars, duplicate dataset paths, and archives without a shapefile.
- Preserve the source ZIP/artifact according to the existing upload lifecycle; remove only temporary extraction directories and failed staging tables.

## Implementation plan

1. Extend `UploadSession` and response schemas with an independent import lifecycle (`not_applicable`, `pending`, `processing`, `completed`, `failed`, `cancelled`) and progress/result fields.
2. Generate an Alembic migration from SQLModel changes, then add the strictly necessary schema operation for `geodata` because dynamic imported tables are not SQLModel entities.
3. Add secure shapefile ZIP inspection/extraction and a batch PostGIS importer that uses parameterized SQL, deterministic identifiers, validation, CRS conversion, staging, and atomic publication.
4. Add a bound Celery import task with retries, cancellation-aware progress updates, idempotency, artifact materialization, and cleanup.
5. Keep completed uploads in the existing `uploaded` state and expose an explicit endpoint that dispatches import only after a ZIP is fully available.
6. Extend upload status and add start/retry/cancel endpoints.
7. Create/update a `LayerType.postgis` Layer on success and integrate table ownership into layer delete preview/deletion.
8. Add unit and integration-style tests for validation, naming, dispatch, task state, status responses, and cleanup behavior.
9. Publish user/developer documentation and update the repository knowledge graph.
10. Support multiple shapefile datasets per ZIP and expose per-table results for Dashboard integration.
11. Preserve the original `Process` action and make PostGIS import an independent, user-triggered action.

## Verification

- Run targeted tests for the importer and upload endpoints.
- Run the full test suite.
- Run Python compilation/static import checks.
- Run Alembic migration checks where the configured database permits it.
- Run `graphify update .` after implementation.
