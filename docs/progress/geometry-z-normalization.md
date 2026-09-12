Related Plan: [Geometry Z normalization](../plans/geometry-z-normalization.md)

# Progress

Status: complete

- [x] Normalize 3D geometry labels for GeoServer styles.
- [x] Normalize derived PostGIS and vector-tile geometries to XY.
- [x] Add and run regressions.
- [x] Identify retry failures caused by persisted `* Z` style keys.
- [x] Normalize legacy style keys during rendering; focused regression suite
  passes (8 tests) and the worker was restarted to load the change.
