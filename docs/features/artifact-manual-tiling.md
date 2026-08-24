# Artifact manual tiling

Plan: [artifact-manual-tiling](../plans/artifact-manual-tiling.md)  
Progress: [artifact-manual-tiling](../progress/artifact-manual-tiling.md)

`POST /api/v1/uploads/artifact` now stages a verified `upload_api` artifact as an upload session with status `uploaded`. It retains the artifact lease and returns the TileServer upload and layer IDs, but does not start a Celery task.

Clients then call `POST /api/v1/uploads/{upload_id}/tile` with their selected `output_format` and optional `max_zoom`, exactly as they do for legacy uploads. TileServer records those options, switches the session to `processing`, and queues tiling. The worker releases the artifact lease after successful tiling or after its final failed retry.
