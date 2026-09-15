# Feature: Local Pre-rendered Legends

**Related:** [Plan](../plans/legend-prerender.md) · [Progress](../progress/legend-prerender.md)

## Apa yang dilakukan

Endpoint `GET /layers/{layer_id}/legend` kini juga memberikan legenda untuk tipe
layer yang tidak punya legenda server-side — dengan merender PNG lokal
menggunakan Pillow (dependency yang sudah ada) dan menyajikannya lewat static
mount `/tiles/...` yang sudah ada.

## Tipe layer yang didukung

| Layer type | Sumber legenda |
|---|---|
| `wms` | `GetLegendGraphic` (server) |
| `wmts` | `GetLegendGraphic` via WMS (server) |
| `esri_mapserver` / `esri_imageserver` / `esri_featureserver` / `esri_tileserver` | Esri REST `/legend` (server) |
| `mvt`, `vector`, `geojson`, `kml` | PNG dirender lokal dari `file_metadata.style` |
| `tile` (raster) | PNG dirender lokal dari statistik sumber (colormap atau gradien min→max) |
| `wfs`, `postgis`, `esri_vectortileserver` | tidak tersedia |

## Cara kerja render lokal

Pertama kali endpoint dipanggil untuk tipe local, legenda dirender dan disimpan
ke `TILES_DIR/{layer_id}/legend.png`, lalu dijawab dengan
`legend_url: /tiles/{layer_id}/legend.png` (`format: image/png`). Render
berikutnya dipakai dari cache, dan di-render ulang hanya jika fingerprint
berubah:

- **Vector** (`mvt`/`vector`/`geojson`/`kml`) — fingerprint dari hash style;
  satu baris swatch per geometri (Point = lingkaran, LineString = garis,
  Polygon = kotak) memakai warna/opacity/pattern dari style. Menerima baik JSON
  geometry-keyed mentah maupun wrapper editor `{mode, simple, ...}`.
- **Raster** (`tile`) — fingerprint dari ukuran + mtime file sumber. Jika raster
  punya colormap → deretan swatch diskret; jika tidak → bar gradien min→max
  dengan label angka.

Jika file sumber tidak tersedia / gagal dirender, response `available: false`
dengan `detail` penjelasan.

## Konsumsi

```json
GET /layers/{id}/legend
{
  "layer_id": "...",
  "layer_type": "vector",
  "available": true,
  "legend_url": "/tiles/{id}/legend.png",
  "format": "image/png",
  "detail": "Rendered locally from layer style"
}
```

## Perubahan kode

- `app/infrastructure/services/legend_renderer.py` — renderer Pillow murni.
- `app/usecases/get_layer_legend.py` — handler local baru.
- `app/usecases/layer_source.py` — resolver path sumber bersama (dipakai juga
  oleh sync field), hasil ekstraksi dari `get_layer_fields.py`.
- `app/api/v1/endpoints/layers.py` — endpoint meneruskan `session_repo`.