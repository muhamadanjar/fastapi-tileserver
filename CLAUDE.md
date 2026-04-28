# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run dev server
uvicorn app.main:app --reload

# Copy and configure environment
cp .env.example .env
```

No test suite or linter is configured.

## Architecture

Clean Architecture layered structure:

- **`app/api/v1/endpoints/`** — HTTP layer. Currently one endpoint: `POST /upload-and-tile` that accepts a geospatial file and immediately delegates to the use case.
- **`app/usecases/`** — Orchestration. `ProcessUploadUseCase` saves the file, derives a `layer_id`, then queues tiling as a FastAPI `BackgroundTask`.
- **`app/infrastructure/services/`** — Side effects:
  - `FileService` — saves uploads to `data/uploads/`, extracts ZIPs to find `.shp` files, returns `(Path, file_type)`.
  - `TilingService` — dispatches to `VectorTiler` or `RasterTiler`, writes PNG tiles to `data/tiles/<layer_id>/{z}/{x}/{y}.png`.
- **`app/domain/schemas.py`** — Pydantic models shared across layers.
- **`app/core/config.py`** — `Settings` (pydantic-settings) reads `.env`; exposes `UPLOAD_DIR`, `TILES_DIR`, `DATABASE_URL`.

### Tile generation flow

1. Upload hits `POST /upload-and-tile` → `ProcessUploadUseCase.execute()`
2. `FileService.save_upload()` persists the file; ZIP shapefiles are extracted and the `.shp` path is returned.
3. `TilingService.process_tiling()` runs in background:
   - **Vector** (`VectorTiler`): loads with GeoPandas, reprojects to EPSG:3857, iterates `mercantile.tiles()` over data bounds, renders each tile with matplotlib → PNG.
   - **Raster** (`RasterTiler`): opens with rasterio, auto-detects max zoom from GSD (`log2(156543 / pixel_res)`), reprojects each tile to EPSG:3857 with bilinear resampling → PNG.
4. Tiles are served statically at `/tiles/<layer_id>/{z}/{x}/{y}.png` via `StaticFiles`.

### Supported input formats

| Format | Type |
|---|---|
| `.shp`, `.geojson`, `.json`, `.gpkg`, `.kml` | vector |
| `.zip` (containing `.shp`) | vector |
| `.tif`, `.tiff`, `.img`, `.png`, `.jpg` | raster |

### PostGIS source (not yet wired to an endpoint)

`TilingService.process_tiling()` is designed to also accept a PostGIS config dict as `source_input`. The database connection string is assembled from `.env` vars (`DB_USER`, `DB_PASS`, `DB_HOST`, `DB_PORT`, `DB_NAME`).
