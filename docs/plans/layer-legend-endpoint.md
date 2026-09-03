# Plan: Layer Legend Endpoint

Progress: [layer-legend-endpoint](../progress/layer-legend-endpoint.md)

## Goal

Provide one stable endpoint for clients to request a layer legend without needing
to understand every upstream service URL convention.

## Design

1. Add `GET /layers/{layer_id}/legend`.
2. Build a native `GetLegendGraphic` URL for WMS layers, using the published
   GeoServer layer name or the configured WMS `layers` parameter.
3. Build ArcGIS REST legend URLs for `esri_mapserver` and `esri_imageserver`,
   the two ArcGIS service types that expose a native legend resource.
4. Return a typed `available: false` response for layer types that have no
   server-side legend, rather than returning an invalid URL.
5. Cover URL construction and endpoint error handling with focused tests, and
   document the response contract in the API reference.
