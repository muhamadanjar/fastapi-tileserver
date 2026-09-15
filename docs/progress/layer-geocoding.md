# Progress: Layer Geocoding Endpoint

Related Plan: [Layer Geocoding](../plans/layer-geocoding.md)

## Tasks

- [x] Agree on design + API surface (grill session)
- [x] Add Nominatim + geocoding settings
- [x] Nominatim client (forward + reverse)
- [x] Usecase: reverse per feature (row index)
- [x] Usecase: forward per-layer proximity
- [x] Usecase: global forward
- [x] Schemas + endpoints + router registration
- [x] Runnable check (`tests/test_geocoding_helpers.py`)
- [x] Feature docs (Definition of Done) → `docs/features/layer-geocoding.md`

## Verifikasi

- `venv/bin/python tests/test_geocoding_helpers.py` — semua helper checks pass
  (haversine, radius bbox, representative point GeoJSON/Esri).
- Live smoke test Nominatim forward ("Monas Jakarta") + reverse berhasil.
- OpenAPI: `/api/v1/layers/{layer_id}/geocoding` dan `/api/v1/geocoding`
  terdaftar tanpa konflik.