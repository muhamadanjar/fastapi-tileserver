# Fitur: Layer Geocoding

Related: [Plan](../plans/layer-geocoding.md) · [Progress](../progress/layer-geocoding.md)

## Gambaran

Geocoding atas features layer, didukung **Nominatim (OSM)**, dua arah:

- **Reverse** — dari titik feature dapatkan alamat (point → address).
- **Forward** — dari teks bebas (nama tempat / alamat) dapatkan features terdekat.

Nominatim dipanggil live per request, tanpa cache. Perhatikan rate-limit
Nominatim (~1 req/s); cocok untuk penggunaan internal, bukan load tinggi.

## Endpoint

### 1. Reverse geocoding per feature

```
GET /api/v1/layers/{layer_id}/geocoding?feature_index=3
```

Mengambil geometri feature pada row index 0-based `feature_index`, lalu
reverse-geocode koordinatnya melalui Nominatim.

Response:

```json
{
  "feature_index": 3,
  "longitude": 106.8272,
  "latitude": -6.1754,
  "address": {
    "display_name": "RW 02, Gambir, Central Jakarta, ...",
    "lon": 106.8284,
    "lat": -6.1754,
    "address": { "neighbourhood": "RW 02", "suburb": "Gambir", ... }
  }
}
```

- `feature_index` di luar jangkauan → `404`.
- Layer tanpa geometri point yang bisa diquery → `422` dengan alasan.

### 2. Forward geocoding per layer (proximity)

```
GET /api/v1/layers/{layer_id}/geocoding?text=monas&radius=500&limit=20
```

- Teks di-forward-geocode ke koordinat (Nominatim).
- Features dalam bbox radius `radius` (meter) di sekitar koordinat diambil.
- Dihitung jarak great-circle (haversine) tiap feature dari titik geocoded.
- Sorted nearest-first, dibatasi `limit`.

Response:

```json
{
  "layer_id": "layer-xyz",
  "text": "monas",
  "geocoded": { "display_name": "National Monument, ...", "lon": 106.8271, "lat": -6.1754, "address": {...} },
  "count": 1,
  "matches": [
    { "feature_index": 3, "distance_m": 42.1, "properties": {...}, "longitude": 106.8272, "latitude": -6.1754 }
  ]
}
```

### 3. Forward geocoding global

```
GET /api/v1/geocoding?text=monas&radius=500&limit=5
```

Sama seperti per-layer, tetapi diiterasi ke semua layer aktif/visible yang
geocodable. Hasil digroup per layer:

```json
{
  "text": "monas",
  "geocoded": {...},
  "layers": [
    { "layer_id": "layer-abc", "layer_name": "Monumen Nasional", "count": 2, "matches": [...] }
  ]
}
```

## Layer yang didukung

- **Vector lokal** (SHP/GeoJSON/KML/GPKG, `file_type=vector`) — dibaca via
  geopandas, CRS dinormalisasi ke WGS84.
- **Survey project (published)** — type `geojson` dengan `file_metadata.project_id`,
  features diambil dari tabel `features` (urutan `created_at`).
- **WFS** — `GetFeature` dengan bbox / startIndex (WFS 2.0 & 1.x).
- **Esri FeatureServer / MapServer** — `/query` dengan envelope / resultOffset,
  `outSR=4326`.

Layer render-only (raster, WMS, WMTS, tile, mvt, kml, esri_tileserver dll.)
tidak geocodable → `422`.

## Geometri non-point

Untuk LineString/Polygon digunakan **representative point** (karakteristik
shapely untuk GeoJSON; centroid ring untuk Esri), sehingga reverse geocoding
tetap menghasilkan satu alamat yang masuk akal.

## Konfigurasi

| Variabel | Default | Keterangan |
|---|---|---|
| `NOMINATIM_URL` | `https://nominatim.openstreetmap.org` | Base URL instans Nominatim |
| `NOMINATIM_TIMEOUT` | `10` | Timeout request (detik) |
| `NOMINATIM_USER_AGENT` | `tileserver-api` | User-Agent; ganti bila perlu identifikasi diri |