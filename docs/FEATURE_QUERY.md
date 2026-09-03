# Feature Query Implementation

Query layer feature data by coordinate across all layer types.

## Overview

**Endpoint:** `GET /api/v1/layers/{layer_id}/features?lon={lon}&lat={lat}`

**Response:** `FeatureQueryResponse`
```json
{
  "type": "vector|raster",
  "count": 0,
  "features": [{...}],    // vector only
  "values": {"band_1": X}, // raster only
  "query_hint": "client"  // optional: frontend reads rendered features (no backend query)
}
```

## Implementation (2026-06-10)

**File:** `app/usecases/getinfo_layer.py`

**Class:** `QueryLayerFeaturesUseCase`

Centralized usecase handling all layer types:

```python
usecase = QueryLayerFeaturesUseCase(layer_repo, session_repo)
response = await usecase.execute(layer_id, lon, lat)
```

## Layer Type Support

| Layer Type | Source | Handler | Response |
|---|---|---|---|
| **tile** | Local (vector/raster) | GeoPandas / Rasterio | vector/raster |
| **vector** | Local (vector) | GeoPandas | vector |
| **raster** | Local (raster) | Rasterio | raster |
| **wms** | Remote WMS service | WMS GetFeatureInfo proxy | vector |
| **wmts** | Remote WMTS service | WMTS GetFeatureInfo (KVP, mercantile tile calc) | vector |
| **wfs** | Remote WFS service | Deck.gl direct (FE) / WFS GetFeature proxy (BE fallback) | vector |
| **mvt** | Tile data | Deck.gl (no backend query) | — |
| **geojson** | GeoJSON file | Deck.gl (no backend query) | — |
| **kml** | KML file | Deck.gl (no backend query) | — |
| **esri_featureserver** | Esri API | Deck.gl (no backend query) | — |
| **esri_vectortileserver** | Esri tiles | Deck.gl (no backend query) | — |
| **esri_mapserver** | Remote Esri MapServer | Esri `identify` endpoint proxy | vector |
| **esri_tileserver** | Remote Esri (cached MapServer) | Esri `identify` endpoint proxy | vector |
| **esri_imageserver** | Remote Esri ImageServer | Esri `identify` endpoint proxy | raster (band values) |

## Adapter Registry (2026-09-01)

Per-layer-type behaviour lives in strategy adapters in `app/usecases/getinfo_adapters.py`,
replacing the old `if/elif` dispatch chain so adding/tuning a layer type is one file.
The usecase (`QueryLayerFeaturesUseCase`) only resolves the adapter for a layer, calls it,
then applies shared `file_metadata.fields` filtering.

For render-only types (`mvt`, `geojson`, `kml`, `esri_featureserver`, `esri_vectortileserver`)
the adapter returns an empty result with `query_hint="client"`. The frontend uses that flag
(alongside `layer_type`) to read features from its own already-loaded tiles
(e.g. Deck.gl/MapLibre `querySourceFeatures`) instead of issuing a backend query.

## Esri Identify (2026-06-10)

**MapServer / TileServer:** `_query_esri_mapserver()`
- Base URL diambil sampai `/MapServer` (strip `/tile/{z}/{y}/{x}` + query)
- `GET {base}/identify?geometry={lon},{lat}&geometryType=esriGeometryPoint&sr=4326&layers=all&tolerance=5&...&f=json`
- Setiap result attributes jadi feature, dengan key `_layer` = layerName

**ImageServer:** `_query_esri_imageserver()`
- `GET {base}/identify?geometry={json point}&f=json`
- Pixel value di-parse jadi `{band_1: X, ...}` (type raster)

## WMTS GetFeatureInfo (2026-06-10)

**Handler:** `_query_wmts()` — best-effort KVP
- Hitung TILEROW/TILECOL via `mercantile.tile(lon, lat, 15)` + pixel I/J dalam tile
- `SERVICE=WMTS&REQUEST=GetFeatureInfo&TILEMATRIXSET=EPSG:3857&INFOFORMAT=application/json`
- Layer name dari URL params `layer` atau `file_metadata.layers`
- Tidak semua WMTS server support — fallback empty response

## Frontend Fixes (2026-06-10)

`tile-map.tsx`:
- `hitLayer` matching diganti generic `info.layer.id.endsWith(layer_id)` — sebelumnya WMS/WMTS/vector/WFS/Esri raster tidak pernah match → get info tidak keluar
- Esri mapserver/tileserver/imageserver: `pickable: false` → `true` (sebelumnya tidak bisa diklik)
- WFS masuk direct-properties branch (decoded deck.gl, tanpa API call)

## Vector Query (Local Files)

**Handler:** `_query_vector()` - GeoPandas

1. Read vector file (GeoJSON, Shapefile, GPKG, etc)
2. Convert CRS to EPSG:4326 if needed
3. Create Point(lon, lat)
4. Find features where geometry.contains(point)
5. Return feature properties

**Field filtering (2026-06-10 — berlaku SEMUA layer type):**
- Centralized di `_apply_field_configs()`, dipanggil dari `execute()` setelah dispatch
- `file_metadata.fields` (FieldConfig: original, label, visible) → hanya field `visible: true` yang di-return
- Key response tetap pakai nama **original** — frontend yang map ke label saat render (panel lookup pakai `config.original`)
- Vector: filter properties per feature (key `_layer` dari Esri identify selalu lolos)
- Raster: filter band values hanya jika ada band yang match config (tidak blank-kan response)
- Tanpa config → semua properties di-return

## Raster Query (Local Files)

**Handler:** `_query_raster()` - Rasterio

1. Open raster file
2. Convert lon/lat to row/col pixel indices
3. Check bounds (inside raster extent?)
4. Sample pixel values at coordinate
5. Return `{band_1: val, band_2: val, ...}`

## WMS Query (Remote Service)

**Handler:** `_query_wms()` - WMS GetFeatureInfo proxy

**Process:**
1. Get layer name from metadata:
   - First try: `file_metadata.geoserver.layer_name`
   - Fallback: `file_metadata.layers`
   - Final fallback: `params.layers` from URL
2. Build GetFeatureInfo request:
   - WMS version detection (1.3.0 vs 1.1.1)
   - Pixel coordinates: `i`, `j` (v1.3) or `x`, `y` (v1.1) — center of 512×512
   - BBOX kecil `±0.005°` di sekitar klik (~2 m/pixel) — bbox besar membuat
     fitur kecil sub-pixel dan tidak pernah match
   - Info format: `application/json`
3. Send request to WMS server
4. Parse JSON response
5. Extract feature properties

**Supported versions:**
- WMS 1.3.0 (CRS param) — **axis order lat,lon** untuk EPSG:4326 (wajib per spec;
  bbox lon,lat menghasilkan response kosong)
- WMS 1.1.1 (SRS param) — axis order lon,lat

## WFS Query (Remote Service)

**Handler:** `_query_wfs()` - WFS GetFeature proxy

**Process:**
1. Get layer name (typeName)
2. Build GetFeature request:
   - BBOX filter around coordinate
   - Output format: `application/json`
3. Send request to WFS server
4. Parse JSON response
5. Extract feature properties

## Integration Points

### Backend
- **Endpoint:** `/api/v1/layers/{layer_id}/features`
- **Usecase:** `QueryLayerFeaturesUseCase`
- **Repos:** `LayerRepository`, `UploadSessionRepository`

### Frontend (Dashboard)
- **API call:** `tileApi.queryFeatures(layer_id, lon, lat)`
- **File:** `features/geo/tile/api.ts:60`
- **Handler:** `tile-map.tsx:807` (handleDeckClick)
- **Display:** `ClickInfoPanel` (lines 541-709)

**Frontend decision:**
```typescript
// Direct from Deck.gl (no API call)
if (['mvt', 'geojson', 'kml', 'esri_featureserver', 'esri_vectortileserver'].includes(type))
  featureData = {type: 'vector', features: [properties]}

// Via backend query
else
  featureData = await tileApi.queryFeatures(layer_id, lon, lat)
```

## Response Format

### Vector Response
```json
{
  "type": "vector",
  "count": 2,
  "features": [
    {"name": "Feature 1", "population": 1000},
    {"name": "Feature 2", "population": 2000}
  ]
}
```

### Raster Response
```json
{
  "type": "raster",
  "count": 1,
  "values": {
    "band_1": 125.5,
    "band_2": 130.2,
    "band_3": 128.8
  }
}
```

### No Data Response
```json
{
  "type": "vector|raster",
  "count": 0,
  "features": []  // or no field if raster
}
```

## Error Handling

All exceptions caught and return empty response:
- Vector query error → `{type: 'vector', count: 0, features: []}`
- Raster query error → `{type: 'raster', count: 0, values: {}}`
- WMS/WFS error → `{type: 'vector', count: 0, features: []}`

Errors logged to stdout: `[vector] Query error: ...`

## Usage Examples

### Query Vector Layer
```bash
curl "http://localhost:8000/api/v1/layers/layer-123/features?lon=116.5&lat=-1.2"
```

### Query Raster Layer
```bash
curl "http://localhost:8000/api/v1/layers/raster-456/features?lon=116.5&lat=-1.2"
```

### Query WMS Layer
```bash
curl "http://localhost:8000/api/v1/layers/wms-789/features?lon=116.5&lat=-1.2"
```

## Testing

**Vector:**
- Upload GeoJSON/Shapefile
- Click map → properties appear

**Raster:**
- Upload GeoTIFF
- Click map → band values appear

**WMS:**
- Create external WMS layer
- Ensure `file_metadata.layers` has correct layer name
- Click map → WMS GetFeatureInfo data appear

**WFS:**
- Create external WFS layer
- Click map → WFS GetFeature data appear

## Future Enhancements

- [ ] WMTS feature query (limited support)
- [ ] Esri MapServer query support
- [ ] Geometry return in feature response (for highlight)
- [ ] Caching for repeated queries
- [ ] Batch query (multiple coordinates)
- [ ] Custom query filters
