# Geometry Z normalization

Related Plan: [Geometry Z normalization](../plans/geometry-z-normalization.md)
Progress Archive: [geometry-z-normalization](../progress/geometry-z-normalization.md)

Shapefile inputs may have a Z or M ordinate. TileServer retains the source file
but produces 2D derived outputs:

- Batch inspection maps `Point Z`, `LineString Z`, `Polygon Z`, and M/ZM
  variants to the matching 2D style family before building an SLD for GeoServer.
- PostGIS import applies `ST_Force2D` to every WKB geometry before inserting it
  into the EPSG:4326 geometry column.
- Raster-vector and MVT tilers drop Z/M from their in-memory GeoDataFrame before
  calculating bounds, spatial indexes, or tiles.
- Retry rendering normalizes legacy persisted style keys such as `Polygon Z`
  before passing them to GeoServer SLD generation, so old failed batches can be
  retried without a new upload.

This prevents Z dimensions from failing PostGIS or generating unsupported style
keys, while intentionally leaving the original uploaded archive unchanged.
