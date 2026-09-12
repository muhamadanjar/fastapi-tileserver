Related Plan: [Upload Layer-Type Detection Plan](../plans/upload-layer-type-detection.md)

# Upload Layer-Type Detection Progress

- [x] Initialize plan and progress documentation.
- [x] Add `shp` to `LayerType` enum.
- [x] Extend `/uploads/{id}/save`: allow `.zip`, validate `.shp` member inside, store `data.zip`, set `layer_type="shp"`.
- [x] Verify bbox extraction from zip (`extract_bbox_from_file` already handles `.zip` via geopandas VSIZIP; `_LOCAL_VECTOR_TYPES`/consumers untouched).
- [x] Write final feature documentation.

Notes:
- Layer-type mapping extracted to `FileService.save_layer_type()` (pure function) so it is unit-testable without a DB. See `tests/test_save_layer_type.py`.
- `LayerType` is a plain `str` column — enum addition needs no Alembic migration.
- Existing consumers unaffected: `geocoding.py:292` still sees `geojson` for `.geojson`; `overlay_analysis`/legend/getinfo already tolerate `shp` as a vector-family value where relevant.