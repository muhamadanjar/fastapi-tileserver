# Feature: Vector Overlay Analysis

Plan: [vector-overlay-analysis](../plans/vector-overlay-analysis.md)
Progress: [vector-overlay-analysis](../progress/vector-overlay-analysis.md)

## Overview

Vector overlay analysis lets users combine and manipulate spatial layers using
standard GIS operations: Intersection, Union, Dissolve, Clip, Difference, and
Buffer. Results appear on the map as ephemeral layers — the user decides whether
to keep or discard them.

## How it works

1. User picks one or two input layers (from `layers` table, survey project
   features, or freshly uploaded files).
2. User picks an operation compatible with the selected layers' geometry types.
3. System validates inputs, executes the operation with GeoPandas/Shapely.
4. Result is saved as a GeoJSON file + ephemeral Layer record.
5. User views result on map, then saves it permanently or discards it.

## Operations

| Operation | Inputs | Output | Notes |
|---|---|---|---|
| Intersection | 2 layers | Overlapping area | Polygon+polygon, polygon+line, polygon+point |
| Union | 2 layers | Merged geometry | Same geometry type for both inputs |
| Dissolve | 1 layer | Merged boundary | Optional group-by attribute |
| Clip | 2 layers | A cut by B | Layer B must be polygon |
| Difference | 2 layers | A minus overlap with B | Polygon only |
| Buffer | 1 layer | Distance zone | Distance in meters/km/feet/miles |
| Symmetric Difference | 2 layers | Parts not overlapping | Same geometry type for both inputs |
| Simplify | 1 layer | Fewer vertices | Tolerance in geometry units |
| Spatial Join | 2 layers | B's attributes onto A | Predicate: intersects/within/contains/touches/crosses/overlaps |
| Centroid | 1 layer | Point per feature | Output is always point |

## API Reference

Intersection optionally supports per-pair area and percentages with
`calculate_area=true`. See [Polygon intersection area metrics](geospatial-analysis-enhancements.md)
for input validation, IDs, source snapshots, and request examples.

Base path: `/api/v1/analysis`

### List operations
```
GET /api/v1/analysis/operations
```
Returns all operations with metadata: input requirements, compatible geometry
types, phase, optional parameters.

### List available layers
```
GET /api/v1/analysis/layers
```
Returns vector layers that can be used as analysis input.

### Validate analysis
```
POST /api/v1/analysis/validate
{
  "operation": "intersection",
  "input_layer_a_id": "layer-1",
  "input_layer_b_id": "layer-2"
}
```
Pre-checks geometry compatibility and returns applicable operations for the
given geometry pair.

### Run analysis
```
POST /api/v1/analysis/run
{
  "operation": "buffer",
  "input_layer_a_id": "layer-1",
  "output_name": "Road Buffer 100m",
  "selected_attributes": {"layer_a": ["name"]},
  "buffer_distance": 100,
  "buffer_unit": "meters"
}
```
Response:
```json
{
  "result_layer_id": "analysis_abc123",
  "operation": "buffer",
  "feature_count": 42,
  "skipped_null_geometry": 3,
  "warning": null,
  "bbox": [106.5, -6.3, 107.2, -5.9],
  "geojson_url": "/api/v1/analysis/analysis_abc123/preview"
}
```

### Async execution
```
POST /api/v1/analysis/run
{
  "operation": "dissolve",
  "input_layer_a_id": "layer-1",
  "async_run": true
}
```
Returns immediately with `result_layer_id` + `async_task_id`. Poll progress:
```
GET /api/v1/analysis/status/{result_id}
→ { "status": "pending|processing|done|failed", "feature_count": ..., ... }
```
Requires RabbitMQ + Celery worker running. Sync mode (`async_run=false`,
default) blocks until done.

### Save result (permanent)
```
POST /api/v1/analysis/{result_layer_id}/save
```

### Discard result (delete)
```
DELETE /api/v1/analysis/{result_layer_id}
```

### Cleanup abandoned ephemeral results
```
DELETE /api/v1/analysis/cleanup?ttl_hours=24
```
Deletes ephemeral layers + result files older than TTL. Also available as
Celery task `cleanup_analysis_ephemeral_task` for periodic scheduling.

### Download result
```
GET /api/v1/analysis/{result_layer_id}/download?format=geojson|shp
```
- `geojson` — single GeoJSON file
- `shp` — zipped ESRI Shapefile

## Edge case handling

| Case | Behavior |
|---|---|
| Empty result (no overlap) | Returns empty layer + warning message |
| Same layer as both inputs | Rejected with error |
| Mixed geometry types in one layer | Rejected |
| Null geometry features | Skipped, count logged in response |
| Incompatible geometry pair | Rejected with explanatory error |
| Project layer as input | Features read live from `features` table |
| Async failure | Result row marked `failed`, placeholder layer deleted |

## Domain model additions

- `OverlayOperation` enum — all 10 operation names (Phase 1 + Phase 2)
- `AnalysisResult` table — tracks runs: operation, feature counts, warning,
  result file path, ephemeral flag, status (`pending|processing|done|failed`),
  Celery task id, error message, bbox

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ANALYSIS_ASYNC_THRESHOLD` | 100000 | Future auto-async trigger (feature count) |
| `ANALYSIS_EPHEMERAL_TTL_HOURS` | 24 | Age at which ephemeral results are cleaned up |
