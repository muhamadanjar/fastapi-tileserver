Related Plan: [Shapefile import to PostGIS](../plans/shapefile-postgis-import.md)

# Progress

- [x] Complete design grilling and confirm upload, validation, database, lifecycle, and deletion behavior.
- [x] Initialize linked plan and progress documentation.
- [x] Extend SQLModel, schemas, configuration, and generate the migration.
- [x] Implement secure ZIP validation and atomic batch PostGIS import.
- [x] Add Celery task and centralized dispatch for all upload methods.
- [x] Add import status, retry, and cancellation API behavior.
- [x] Register PostGIS Layers and clean up owned tables on deletion.
- [x] Add and run targeted, regression, migration, and PostGIS integration tests.
- [x] Create final feature documentation and refresh the knowledge graph.
- [x] Extend the importer and response contract for multiple shapefiles per ZIP.
- [x] Add multi-shapefile tests and refresh final documentation.
- [x] Stop automatic dispatch when upload completes.
- [x] Add an explicit start-import endpoint while preserving retry/cancel behavior.
- [x] Update tests and documentation for the manual PostGIS action.
- [x] Refresh the knowledge graph for the manual PostGIS action.

Feature documentation: [Impor shapefile ke PostGIS](../features/shapefile-postgis-import.md)
