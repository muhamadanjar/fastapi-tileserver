# Upload Layer-Type Detection Plan

Related Progress: [Upload Layer-Type Detection Progress](../progress/upload-layer-type-detection.md)

Extend the existing `/uploads/{id}/save` endpoint so an uploaded vector file gets a meaningful `LayerType` instead of only `file_type="vector"`. GeoJSON stays `geojson`, zip-packed shapefiles become a new `shp` type (read straight from the zip, no extraction), and `vector` remains an umbrella category for consumers — never assigned at upload. GeoPackage is out of scope (rarely used).

## Decisions (grilled, agreed)

1. `.geojson`/`.json` → `layer_type="geojson"` (existing). Conceptually vector, but stored concretely so strict consumers like `geocoding.py:292` (`layer.layer_type == "geojson"`) keep working.
2. `.zip` shapefile → new `LayerType.shp`. `.shp` raw upload is not allowed; zipped only.
3. `"vector"` is never stored as `layer_type` on upload — it is the family umbrella used by `overlay_analysis.py:143`, `get_layer_legend._LOCAL_VECTOR_TYPES`, `getinfo_adapters.CLIENT_SIDE_TYPES`.
4. Serving: copy zip to `{TILES_DIR}/{layer_id}/data.zip`, `tile_url_template="/{layer_id}/data.zip"`. No new download endpoint — static `/tiles` mount serves it.
5. Zip is read in place: bbox via `extract_bbox_from_file` (geopandas VSIZIP), content validation via `zipfile.namelist()` — no disk extraction.
6. `.gpkg` skipped (YAGNI).

## Changes

- `app/domain/models.py`: add `shp = "shp"` to `LayerType` (plain str column — no migration).
- `app/presentation/router/api/v1/endpoints/upload.py` `save_layer`:
  - allow `.zip` in addition to `.geojson/.json/.kml`
  - validate the zip contains a `.shp` member, else 422
  - `file_ext` and `layer_type`: k‑ml→kml, geojson/json→geojson, zip→shp
  - store `data.zip` untouched (no extract)

## Out of scope

- GeoPackage support
- Legend/query rendering for `shp` (browser can't read a zip client-side today)
- Endpoint download for the stored zip
- Changing stored `geojson` layers to `vector`
