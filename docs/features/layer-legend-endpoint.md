# Fitur: Layer Legend Endpoint

Related: [Plan](../plans/layer-legend-endpoint.md) · [Progress](../progress/layer-legend-endpoint.md)

## Penggunaan

Panggil `GET /api/v1/layers/{layer_id}/legend` untuk memperoleh legenda layer.
Endpoint tidak meneruskan request atau menyimpan gambar legenda; ia memberikan
URL native yang aman dipakai klien untuk menampilkan legenda.

- Layer `wms` mengembalikan URL WMS `GetLegendGraphic` berformat PNG. Nama
  layer diambil dari `file_metadata.geoserver.layer_name`, lalu fallback ke
  `file_metadata.layers` atau `file_metadata.layer`.
- `esri_mapserver` dan `esri_imageserver` mengembalikan ArcGIS REST
  `{service}/legend?f=pjson`. Klien merender entri legenda dari JSON ArcGIS.
- `tile`, `mvt`, `vector`, `geojson`, `kml`, `postgis`, `esri_featureserver`,
  `esri_tileserver`, dan `esri_vectortileserver` mengembalikan `available: false`,
  karena tidak menyediakan endpoint legenda server-side standar.

Contoh respons WMS:

```json
{
  "layer_id": "layer-xyz",
  "layer_type": "wms",
  "available": true,
  "legend_url": "https://maps.example/geoserver/wms?service=WMS&request=GetLegendGraphic&version=1.3.0&layer=workspace%3Aroads&format=image%2Fpng",
  "format": "image/png"
}
```

Saat `available` bernilai `false`, periksa `detail` untuk alasan dan jangan
berusaha memuat `legend_url`.
