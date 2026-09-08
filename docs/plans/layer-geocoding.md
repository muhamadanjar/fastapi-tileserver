# Plan: Layer Geocoding Endpoint

Progress: [layer-geocoding](../progress/layer-geocoding.md)

## Goal

Provide geocoding over layer features so a client can resolve addresses from
feature points (reverse) and find features near a place name (forward), using
Nominatim (OSM) as the geocoding backend.

## Decisions (confirmed with user)

- **Both directions**: reverse (feature point -> address) and forward (text ->
  nearby features).
- **Provider**: Nominatim / OSM, live per request, no cache, default instance.
- **Forward scope**: both per-layer and global (across active layers).
- **Matching**: proximity by distance — geocode via Nominatim, then query
  features in a small bbox around the result and sort by distance.
- **Reverse output**: Nominatim `display_name` + raw address components.
- **Supported layers**: any layer exposing queryable point geometry — local
  vector (shp/geojson/kml), survey project features (postgis/geojson type),
  WFS, and ESRI FeatureServer/MapServer.
- **Feature identity**: 0-based row index within the layer.

## Endpoints

1. `GET /layers/{layer_id}/geocoding?feature_index=<n>` — reverse geocode a
   single feature by its 0-based row index.
2. `GET /layers/{layer_id}/geocoding?text=<q>&radius=<m>&limit=<n>` — forward:
   Nominatim -> coordinate -> features within bbox -> sorted by distance.
3. `GET /geocoding?text=<q>&limit=<n>` — global forward across active layers,
   grouped by layer.

## Implementation notes

- Read geometry for a row index directly from the source (geopandas for local
  vector) rather than fetching all features.
- Forward matching reuses the bbox-query pattern already present in
  `GetFeaturesInBboxUseCase` (geopandas / WFS GetFeature bbox / ESRI envelope).
- Haverine distance in meters for sorting.
- Nominatim base URL, timeout, and UA configurable via settings with sensible
  defaults.
