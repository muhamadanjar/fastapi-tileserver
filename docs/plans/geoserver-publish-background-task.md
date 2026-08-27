# GeoServer publish as a background task

Related Plan: [GeoServer publish as a background task](./geoserver-publish-background-task.md)
Progress: [geoserver-publish-background-task](../progress/geoserver-publish-background-task.md)

## Goal

`POST /uploads/{upload_id}/geoserver` currently publishes to GeoServer synchronously. Large files (e.g. 15 MB) exceed the proxy request timeout and the caller gets a 502, even though the publish may still succeed server-side. Move the publish into a Celery worker so the endpoint returns immediately and the caller polls the existing `/uploads/{upload_id}/status` endpoint.

## Implementation

1. Add `publish_geoserver_task` to `app/workers/tasks.py`, mirroring `process_tiling_task`'s worker pattern:
   - Resolve artifact vs local source path, publish via `GeoServerService.publish_shp`.
   - Extract bbox/CRS, upsert the layer (WMS) with sync repos, then set upload status `done`.
   - On failure, set status `failed` and retry (max 3).
2. Change the endpoint to validate as today, generate the unique code, mark the session `processing`, store the celery task id, enqueue the task, and return the "started" payload immediately.
3. Client polls `/uploads/{upload_id}/status` until `done`, then reads layer metadata (GeoServer info lives in `layer.file_metadata.geoserver`).