# GeoServer publish as a background task

Related Plan: [GeoServer publish as a background task](../plans/geoserver-publish-background-task.md)
Progress: [geoserver-publish-background-task](../progress/geoserver-publish-background-task.md)

## How it works

`POST /uploads/{upload_id}/geoserver` no longer publishes synchronously. It validates the upload (`.shp`/`.zip`, status `uploaded`/`failed`, source file present), generates the unique layer code, marks the session `processing`, and enqueues `publish_geoserver_task` on the `tileserver` Celery queue. The endpoint then returns immediately with `{"status": "processing"}` — the HTTP request no longer stays open while GeoServer ingests large files, so proxies no longer return 502.

## Worker task behavior

`app/workers/tasks.py::publish_geoserver_task(upload_id, layer_id, code)`:

1. Materializes the source (upload-api artifact lease or local path).
2. Publishes via `GeoServerService.publish_shp`.
3. Extracts bbox/CRS from the file (fallback: GeoServer-recalculated bbox).
4. Upserts the layer as `wms` (tile URL = WMS URL, GeoServer metadata in `file_metadata.geoserver`, bbox columns).
5. Sets upload status `done` and releases the artifact lease.
6. On failure: sets status `failed` with the error message, retries up to 3 times.

## Client usage

1. Call `POST /uploads/{upload_id}/geoserver` → 200 `{"status": "processing"}`.
2. Poll `GET /uploads/{upload_id}/status` until `status` is `done` (read `error_message` if `failed`).
3. Read the published layer (WMS URL, GeoServer metadata) from the layer resource via `layer_id` (`file_metadata.geoserver`).

Cancellation works via the existing `POST /uploads/{upload_id}/cancel` (the celery task id is stored on the session).