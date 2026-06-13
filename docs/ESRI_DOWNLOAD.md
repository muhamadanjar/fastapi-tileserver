# Esri MapServer/FeatureServer Data Download

Download semua data vector dari layer external bertipe `esri_mapserver` / `esri_featureserver` menjadi **GeoJSON + Shapefile (zip)** per sublayer. Berjalan sebagai Celery background task.

## Endpoints

| Method | Path | Keterangan |
|---|---|---|
| `POST` | `/api/v1/layers/{layer_id}/download` | Mulai download (queue Celery task). 409 jika sedang berjalan, 422 jika bukan layer Esri. |
| `GET` | `/api/v1/layers/{layer_id}/download/status` | Status & progress (`file_metadata.download_process`). |
| `GET` | `/api/v1/layers/{layer_id}/download/files` | Daftar file hasil + URL. |
| `DELETE` | `/api/v1/layers/{layer_id}/download` | Cancel download yang sedang berjalan (cooperative). |

File hasil juga bisa diakses langsung via static mount `/downloads/{layer_id}/...`.

## Output

```
data/download/{layer_id}/
  manifest.json                      # ringkasan: sublayers, feature_count, skipped
  {sublayer_id}_{slug}/
    {slug}.geojson                   # FeatureCollection EPSG:4326
    {slug}_shp.zip                   # .shp .shx .dbf .prj .cpg
```

Tiap sublayer pada service menjadi satu folder output sendiri. Sublayer group/raster/non-queryable di-skip dan dicatat di `manifest.json["skipped"]`. Re-download menimpa folder lama.

## Cara kerja pagination

Server Esri membatasi hasil query (`maxRecordCount`, umumnya 1000). Downloader:

1. Ambil semua objectIds: `query?where=1=1&returnIdsOnly=true` (tanpa limit).
2. Query per-batch `objectIds` (POST, batch = `min(maxRecordCount, 1000)`) — kompatibel dengan server lama tanpa `resultOffset`.
3. Jika server balas `exceededTransferLimit`, batch dipecah dua secara rekursif.
4. Format `f=geojson` dipakai bila didukung; fallback ke `f=json` (Esri JSON) + konversi geometri (point/multipoint/polyline/polygon rings) di sisi kita.
5. Retry 3x per batch dengan backoff; selalu `outSR=4326`.

## Status download

Disimpan di `Layer.file_metadata.download_process`:

```json
{
  "status": "pending | processing | done | failed | cancelled",
  "percent": 0,
  "task_id": "...",
  "current_sublayer": "Counties",
  "sublayers_done": 3, "sublayers_total": 4,
  "features_done": 2000, "features_total": 3141,
  "manifest": { "...": "saat done, path relatif ke data/download" }
}
```

## Komponen

- `app/infrastructure/services/esri_downloader.py` — fetch metadata service, enumerasi sublayer, pagination, konversi Esri JSON→GeoJSON, tulis geojson + shapefile zip (geopandas/pyogrio).
- `app/workers/tasks.py` — `download_esri_layer_task` (progress + cooperative cancel via `download_process.status`).
- `app/infrastructure/db/repository.py` — `SyncLayerRepository.update_download_progress` / `get_download_progress`.
- `app/api/v1/endpoints/layers.py` — endpoint trigger/status/files/cancel; delete layer ikut menghapus `data/download/{layer_id}`.
- `app/main.py` — static mount `/downloads`.
- `app/core/config.py` — `DOWNLOAD_DIR = data/download`.

## Catatan

- Nama field shapefile dipotong otomatis ke 10 karakter (batasan format DBF); nama penuh tetap ada di GeoJSON.
- URL layer yang menunjuk satu sublayer (mis. `.../MapServer/3`) hanya men-download sublayer itu.
- SSRF guard (`_validate_url_safety`) diterapkan sebelum fetch service.

## Tes manual

```bash
# layer external contoh
curl -X POST localhost:8000/api/v1/layers/external -H 'Content-Type: application/json' \
  -d '{"filename":"usa","layer_type":"esri_mapserver","source_url":"https://sampleserver6.arcgisonline.com/arcgis/rest/services/USA/MapServer"}'

curl -X POST localhost:8000/api/v1/layers/{id}/download
curl localhost:8000/api/v1/layers/{id}/download/status
curl localhost:8000/api/v1/layers/{id}/download/files
```
