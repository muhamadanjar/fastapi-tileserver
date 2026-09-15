# Polygon Intersection Area Metrics

Plan: [Geospatial analysis enhancements](../plans/geospatial-analysis-enhancements.md)
Progress: [Implementation and verification](../progress/geospatial-analysis-enhancements.md)

## Purpose

Enable `calculate_area` on the existing intersection operation to measure the
overlap of any two polygon layers. No village, flood, facility, or date fields
are required. The default remains `false`, preserving ordinary intersection.

Each output feature represents one input A–B feature pair, with its polygon
intersection, source identifiers, area, and percentages. Disconnected pieces
of the same pair remain a MultiPolygon. Boundary-only contact produces no
output feature. No positive-area matches returns an empty layer and warning.

## Request

Send the same body to `POST /api/v1/analysis/validate` for a preflight check,
then `POST /api/v1/analysis/run` to execute:

```json
{
  "operation": "intersection",
  "input_layer_a_id": "layer-a",
  "input_layer_b_id": "layer-b",
  "calculate_area": true,
  "source_id_field_a": "parcel_id",
  "source_id_field_b": "zone_id",
  "selected_attributes": {
    "layer_a": ["name"],
    "layer_b": ["category"]
  },
  "output_name": "Intersection measurements",
  "async_run": false
}
```

- `calculate_area` is supported only for `intersection` with Polygon/MultiPolygon
  inputs. Unsupported combinations return a validation error.
- The ID fields are optional. When specified, every value must be a unique,
  non-empty string or finite number within that input layer; output IDs are
  strings. An explicitly invalid/missing ID field is rejected, not silently
  replaced. ID-field options require `calculate_area=true`.
- When omitted, IDs are generated as `<run_id>:a:<row>` or `<run_id>:b:<row>`.
  Rows are zero-based within the execution-time input snapshot, not necessarily
  stable database row numbers. Generated IDs are not stable across runs.
- `selected_attributes.layer_a` / `.layer_b` select source fields independently.
  An omitted side keeps all attributes; an empty list keeps none. Selected
  attributes use `a_` / `b_` prefixes in the result to avoid collisions. Legacy
  `a` / `b` selection keys are also accepted. Metrics and source IDs always remain.
- Local uploaded vectors, published survey features, and completed analysis
  results can be inputs through the existing loaders. This enhancement does
  not introduce remote-service or raster input adapters.

`GET /api/v1/analysis/operations` advertises the new optional parameter names.

## Result properties

The run response keeps the existing envelope (`result_layer_id`, `feature_count`,
`geojson_url`, etc.). Retrieve the measurements through that preview URL or
the existing result download endpoint.

| Property | Meaning |
|---|---|
| `src_a_id`, `src_b_id` | IDs identifying the source feature pair |
| `src_a_row`, `src_b_row` | Zero-based source snapshot positions |
| `area_m2` | Intersection area in square meters |
| `area_ha` | `area_m2 / 10000` |
| `pct_a` | `100 × intersection area / full original A feature area` |
| `pct_b` | `100 × intersection area / full original B feature area` |

For A = 100 ha, B = 40 ha, and intersection = 20 ha, properties contain:

```json
{
  "src_a_id": "A",
  "src_b_id": "B",
  "src_a_row": 0,
  "src_b_row": 0,
  "area_m2": 200000.0,
  "area_ha": 20.0,
  "pct_a": 20.0,
  "pct_b": 50.0
}
```

Pair results remain independent even when B features overlap each other.
Summing their areas or percentages is not a unique coverage calculation and
can exceed the area or 100% of A. Each individual pair's percentage is 0–100.
Values retain floating-point precision; round in the UI only.

## Measurement and validation

Both input layers are transformed to the same equal-area CRS, **EPSG:6933**,
for polygon intersection and all area measurements. Result and snapshot
geometries are published in EPSG:4326. This avoids measuring square degrees
or interpreting arbitrary projected coordinate units as meters. EPSG:6933
is the global cylindrical equal-area EASE-Grid 2.0 projection described by
[NSIDC](https://nsidc.org/data/user-resources/help-center/guide-ease-grids).

This is a planar calculation after vertex reprojection, not a geodesic-edge
intersection. CRS must be known. The supported latitude range is 86°S–86°N;
features whose longitude extent exceeds 180° are rejected. Split dateline
crossings into separate features before use. Polar features require another
measurement strategy and are not supported by this option.

Invalid, null, empty, non-polygon, non-finite, and zero-area geometries are
rejected with source IDs/row positions and reasons; they are not silently
repaired or dropped. A completely empty layer with a known CRS is allowed.
During preflight, generated identifiers use the provisional `validation`
scope; actual execution identifiers use that run's ID.

`/validate` reports `valid=false` and errors; synchronous `/run` returns HTTP
400 for input validation failures. Normal operations retain their existing
validation behavior when this option is disabled.

## Source traceability and persistence

`GET /api/v1/analysis/{result_layer_id}/sources` downloads `sources.json`:

- `run_id` and `measurement_crs` identify the execution and measurement method.
- `layer_a` and `layer_b` each contain `layer_id`, `id_field`, `source_crs`, and
  a GeoJSON FeatureCollection in EPSG:4326.
- Each snapshot feature has the matching `id`, a `source_row`, original
  attributes, and geometry. Snapshot attributes are retained even when omitted
  from the displayed result; date attributes serialize as strings.

Snapshots refer to inputs read at execution, including for queued jobs.
They remain available if the source file later changes. Result layer metadata
records the measurement CRS, ID fields, run scope, and snapshot filename under
`file_metadata.analysis.area_metrics`. No database migration is required.

The result and source snapshot share the existing temporary/save/discard/TTL
lifecycle. Saving retains both; discard or TTL cleanup removes both. GeoJSON
and zipped Shapefile downloads retain the computed fields. Computed field names
fit Shapefile's 10-character limit; long user attribute names and long string
values remain subject to Shapefile's format limits. Use GeoJSON and the source
snapshot for lossless field names and source identifiers.

## Async execution

Set `async_run=true` to use the existing Celery flow. Cheap request checks run
before enqueueing; geometry/ID validation and measurement run in the worker
against the inputs available then. Sync and async share the same computation.
Poll `GET /api/v1/analysis/status/{result_layer_id}` using the result layer ID
returned by `/run`. The endpoint also accepts the original analysis result ID
and returns both identifiers.

For this option, a failed worker run retains its inactive placeholder layer
so the result's foreign key and failure status remain valid. Discard/TTL can
remove the failed run and its placeholder together. Existing async retry
policy is unchanged.

Frontend controls and map/table presentation are outside this backend change.
