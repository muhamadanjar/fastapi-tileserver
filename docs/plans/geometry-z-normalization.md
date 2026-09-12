# Geometry Z normalization

Status: active

Related Progress: [geometry-z-normalization](../progress/geometry-z-normalization.md)

## Goal

Accept 3D shapefile geometries for batch WMS, raster/MVT tiling, and PostGIS
import. The source remains untouched; each 2D rendering/import path discards
the Z/M ordinate only for its derived output.

## Plan

1. Normalize inspected geometry labels (`Polygon Z`, `LineString Z`, `Point Z`)
   to their base style types before GeoServer SLD generation.
2. Force 2D on the PostGIS insert expression.
3. Force 2D after vector data is read by both raster-vector and MVT tilers.
4. Add focused regression tests and run the affected test suites.
5. Normalize persisted legacy style keys during rendering, so retries of failed
   batches created before this normalization also succeed.
