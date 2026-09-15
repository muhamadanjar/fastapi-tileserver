# Plan: Vector Overlay Analysis

Progress: [vector-overlay-analysis](../progress/vector-overlay-analysis.md)

## Goal

Provide vector overlay analysis capabilities so users can perform spatial
operations (intersection, union, dissolve, clip, difference, buffer) on layers
within the system. Results display on the map as ephemeral layers; users can
choose to persist them or discard.

## Decisions (confirmed with user)

- **Input sources**: Layer table + Project features + direct upload (full combo).
- **Operations Phase 1**: Intersection, Union, Dissolve, Clip, Difference, Buffer.
- **Operations Phase 2 (noted, not implemented)**: SymDifference, Simplify,
  Spatial Join, Centroid.
- **Incompatible geometry**: Operations disabled/greyed out in UI when geometry
  types are incompatible.
- **Attribute handling**: User selects which attributes from each input layer to
  carry into the result.
- **Output storage**: GeoJSON file saved to `data/uploads/{layer_id}/result.geojson`.
- **Execution**: Synchronous (MVP). Note for future async Celery task.
- **Dissolve**: Full dissolve + optional group-by attribute.
- **Empty intersection**: Return empty layer + warning message (not error).
- **Self-operation**: Reject when layer A == layer B.
- **Mixed geometry types**: Reject, layer must be homogeneous.
- **Null geometry**: Skip features with null geometry, log count skipped.
- **Result layer**: Ephemeral by default — appears on map, user chooses save/delete.
- **Download**: GeoJSON + Shapefile export.
- **Execution engine**: GeoPandas + Shapely (already in requirements.txt).

## Endpoints

1. `GET /api/v1/analysis/operations` — List available operations with metadata
   (input requirements, compatible geometry types, phase).
2. `GET /api/v1/analysis/layers` — List layers available as analysis input
   (vector layers from `layers` table + published project features).
3. `POST /api/v1/analysis/validate` — Pre-check input layers + operation
   compatibility before execution.
4. `POST /api/v1/analysis/run` — Execute analysis, return result layer ID +
   GeoJSON preview.
5. `POST /api/v1/analysis/{result_layer_id}/save` — Persist ephemeral result
   as permanent layer.
6. `DELETE /api/v1/analysis/{result_layer_id}` — Discard ephemeral result.
7. `GET /api/v1/analysis/{result_layer_id}/download?format=geojson|shp` —
   Download result in specified format.

## API Schema

### POST /api/v1/analysis/run

```json
{
  "operation": "intersection|union|dissolve|clip|difference|buffer",
  "input_layer_a_id": "layer-id-1",
  "input_layer_b_id": "layer-id-2",
  "output_name": "My Analysis Result",
  "selected_attributes": {
    "layer_a": ["field1", "field2"],
    "layer_b": ["field3"]
  },
  "buffer_distance": 100,
  "buffer_unit": "meters|kilometers|feet|miles",
  "dissolve_group_by": "field_name"
}
```

### Response

```json
{
  "result_layer_id": "ephemeral-layer-id",
  "operation": "intersection",
  "feature_count": 42,
  "skipped_null_geometry": 3,
  "warning": null,
  "bbox": [west, south, east, north],
  "geojson_url": "/api/v1/analysis/{result_layer_id}/preview"
}
```

## Architecture

### New files

```
app/
  domain/
    models.py                    # + OverlayOperation enum, AnalysisResult model
    schemas.py                   # + AnalysisRequest, AnalysisResponse, OperationInfo
  application/
    analysis/
      __init__.py
      overlay_operations.py      # Core overlay logic (GeoPandas/Shapely)
      geometry_compat.py         # Geometry type compatibility rules
  infrastructure/
    services/
      analysis_service.py        # Orchestration: load layers, run analysis, save result
  api/
    v1/
      endpoints/
        analysis.py              # API endpoints
  workers/
    tasks.py                     # Note: future async analysis task
```

### Geometry compatibility matrix

| Operation | Input A | Input B | Output |
|---|---|---|---|
| Intersection | polygon | polygon | polygon |
| Intersection | polygon | line | line (clipped) |
| Intersection | polygon | point | point (within) |
| Union | polygon | polygon | polygon |
| Clip | polygon | polygon | polygon |
| Clip | line | polygon | line (clipped) |
| Clip | point | polygon | point (within) |
| Difference | polygon | polygon | polygon |
| Buffer | any | - | polygon |
| Dissolve | any | - | same as input |

## Implementation notes

- Load input layers via geopandas `read_file()` from stored GeoJSON/shapefile.
- For Project features: query `features` table, construct GeoDataFrame from
  GeoJSON geometry column.
- Result GeoDataFrame saved as GeoJSON via `to_file()`.
- Layer created with `layer_type=geojson`, `tile_url_template` pointing to
  GeoJSON file.
- Ephemeral layers flagged in `file_metadata.analysis.ephemeral = true`.
- Save action removes ephemeral flag, keeps file.
- Delete action removes file + layer record.

## Phase 2 (implemented — see progress)

- SymDifference — symmetric difference of two layers
- Simplify — reduce vertex count with tolerance parameter
- Spatial Join — join attributes from layer B to layer A by spatial predicate
- Centroid — extract centroid point from each feature
- Async execution via Celery for large datasets
- TTL cleanup for abandoned ephemeral layers
- Support Project features (survey data) as analysis input

## Status

Phase 1 + Phase 2 complete. See [progress](../progress/vector-overlay-analysis.md) and
[feature docs](../features/vector-overlay-analysis.md).
