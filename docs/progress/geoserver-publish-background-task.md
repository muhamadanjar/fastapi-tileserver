Related Plan: [GeoServer publish as a background task](../plans/geoserver-publish-background-task.md)

# Progress

- [x] Confirm the synchronous publish flow and where the 502 originates.
- [x] Add `publish_geoserver_task` to `app/workers/tasks.py`.
- [x] Convert `POST /uploads/{upload_id}/geoserver` to dispatch the task and return immediately.
- [x] Verify Python compilation and targeted checks.

Feature documentation: [GeoServer publish as a background task](../features/geoserver-publish-background-task.md)