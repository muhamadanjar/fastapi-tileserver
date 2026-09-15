# Plan: Local Pre-rendered Legends

**Status:** In progress
**Related:** [Progress](../progress/legend-prerender.md)

## Problem

`GET /layers/{id}/legend` only covers external services (WMS, Esri, WMTS).
Local layer types with no server-side legend (`tile`, `mvt`, `vector`, `geojson`, `kml`)
always return `available: false`, leaving the frontend with nothing to show.

## Goal

Pre-render a legend PNG locally (Pillow, already a dependency) for those types and serve it
through the existing static mount `/tiles/{layer_id}/legend.png`.

## Legend sources per type

| Layer type | Legend source |
|---|---|
| `tile` (raster) | Source GeoTIFF stats: colormap if present, else min→max gradient (rasterio, already a dependency) |
| `mvt`, `vector`, `geojson`, `kml` | `file_metadata.style` (geometry-keyed simple style); fallback to default swatches |
| `wms`, `wmts`, esri* | unchanged (server-side legend URL) |
| `wfs`, `postgis`, `esri_vectortileserver` | unavailable (no local style/source to render) |

## Design

- `app/infrastructure/services/legend_renderer.py` — pure Pillow rendering, no repo deps.
  - `render_vector_legend(style, out_path)`: swatch per geometry (Point circle, LineString line, Polygon box) with labels, from normalized style (handles both raw geometry-keyed JSON and editor-state wrapper `{"mode": ..., "simple": {...}}`).
  - `render_raster_legend(source_path, out_path)`: discrete colormap swatches or min→max gradient bar with numeric labels.
  - Fingerprint sidecar to invalidate stale renders (style hash / source mtime+size).
- `app/usecases/layer_source.py` — extract `resolve_layer_source_path()` shared by field sync and legend (artifact:// handling stays in one place).
- `app/usecases/get_layer_legend.py` — new local handlers; returns `legend_url=/tiles/{layer_id}/legend.png`, `format=image/png`.

## Out of scope

- SLD parsing for vector legends.
- Legends for `wfs`/`postgis` (no styling info server-side).
- Frontend changes.

## Verification

- Extend `tests/test_layer_legend.py`: vector style → rendered URL; editor-state wrapper normalized; raster without source → unavailable; fingerprint regeneration.
- Run `pytest tests/test_layer_legend.py`.