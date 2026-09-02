# Universal Layer BBox

Active Progress: [Implementation progress](../progress/universal-layer-bbox.md)

## Objective

Make layer extents and bbox queries capability-aware across every declared
`LayerType`, without claiming that render-only services expose feature data.

## Design

- Keep `POST /layers/{layer_id}/sync-bbox` as the canonical way to persist a
  WGS84 extent. It must accept a valid manual extent for every layer type.
- Extend automatic extent extraction with local vector/raster files and remote
  WMS, WMTS, WFS, GeoJSON/KML, and ESRI service metadata where available.
- Replace the vector-only bbox-feature guard with a dispatcher. Vector-backed
  sources return attribute records; raster-backed sources return a deliberate
  `not_queryable` result until raster zonal statistics are introduced.
- External render-only and unsupported sources return an explicit capability
  result instead of an empty feature collection, so clients can distinguish
  "no matching features" from "this service cannot be queried".

## Scope and acceptance criteria

1. Every `LayerType` has an explicit bbox-query capability or reason.
2. Every `LayerType` can receive a validated manual bbox.
3. Automatic bbox sync handles supported local/remote sources and reports an
   actionable unavailable reason for the remainder.
4. Endpoint responses and tests cover vector, raster, WFS/ESRI capability
   paths, and render-only fallback behavior.
5. User-facing documentation explains the response contract and limitations.
