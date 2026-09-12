# Upload Layer-Type Detection

Related Plan: [Upload Layer-Type Detection Plan](../plans/upload-layer-type-detection.md)
Related Progress: [Upload Layer-Type Detection Progress](../progress/upload-layer-type-detection.md)

## What it does

`POST /uploads/{id}/save` now stores a meaningful `layer_type` per file format instead of only `file_type="vector"`:

| Uploaded file | Stored `layer_type` | Stored file |
|---|---|---|
| `.geojson` / `.json` | `geojson` | `{TILES_DIR}/{layer_id}/data.geojson` |
| `.kml` | `kml` (converted to GeoJSON on store) | `data.geojson` |
| `.zip` (shapefile) | `shp` | `data.zip` (stored as-is, never extracted) |

`shp` is a new member of the `LayerType` enum. `vector` stays an umbrella category used by consumers (`overlay_analysis`, legend, getinfo) — it is never stored as `layer_type` at upload, so strict checks like `layer.layer_type == "geojson"` keep working.

## How to use

1. Upload a shapefile as a `.zip` (raw `.shp` files are not accepted — companion files `.dbf`/`.shx` must travel inside the zip).
2. `POST /uploads/{id}/save` — it validates the zip actually contains a `.shp` member (422 otherwise), copies it to `data.zip`, and extracts the bbox in place (geopandas reads the zip directly, no disk extraction).
3. The layer's `tile_url_template` is `/{layer_id}/data.zip`, served by the static `/tiles` mount.

## Notes

- The zip → layer-type/extension mapping lives in the pure function `FileService.save_layer_type()` — unit-tested in `tests/test_save_layer_type.py`.
- No DB migration: `LayerType` is a plain string column.
- GeoPackage is intentionally unsupported for now (rarely used). Shapefile PostGIS import (`POST /uploads/{id}/import`) is unchanged and still optional on the same zip.