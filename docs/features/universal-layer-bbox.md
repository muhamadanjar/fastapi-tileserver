# Universal Layer BBox

Related Plan: [Universal Layer BBox](../plans/universal-layer-bbox.md)  
Implementation record: [Progress](../progress/universal-layer-bbox.md)

## BBox synchronization

Use `POST /layers/{layer_id}/sync-bbox` to store an extent in WGS84. A client
may always send a validated manual `bbox: [west, south, east, north]` for any
layer type. When omitted, the service extracts the extent from the local source
or remote service metadata.

Automatic extraction supports local vector/raster files, WMS, WMTS, WFS,
GeoJSON, KML, and ESRI service metadata. A source that has no discoverable
extent returns HTTP 422; send a manual bbox in that case.

## Querying data inside a bbox

`GET /layers/{layer_id}/features/bbox?west=...&south=...&east=...&north=...`
returns up to 200 records by default (maximum 500). The response now exposes
its capability explicitly:

```json
{
  "layer_id": "…",
  "count": 0,
  "exceeded": false,
  "features": [],
  "queryable": false,
  "reason": "This render-only layer does not expose a standard bbox feature query."
}
```

`queryable: true` is returned for local vector data, WFS, and concrete ESRI
MapServer/FeatureServer sublayers. `features` contains attributes only; the
geometry is not returned. The request respects `file_metadata.fields` visibility
configuration.

Raster, WMS/WMTS, tile/MVT, ESRI tile/vector-tile, and unconfigured PostGIS
layers return `queryable: false` with a reason. These sources need a raster
statistics, service-specific feature-info, or PostGIS adapter before they can
return an authoritative collection of features for an area.
