# GeoServer Artifact Pull URL

Plan: [GeoServer Artifact Pull URL](../plans/geoserver-artifact-pull-url.md)  
Progress: [implementation progress](../progress/geoserver-artifact-pull-url.md)

## How publishing works

For an artifact with an active Upload API lease, the GeoServer worker downloads
the content through Upload API into a temporary worker file, then sends the ZIP
bytes to GeoServer REST `file.shp`. This keeps the Upload API storage backend
independent from GeoServer's REST upload.

A shapefile is a multi-file format (`.shp`, `.dbf`, `.shx`, and optionally
`.prj`), so GeoServer requires a ZIP archive.

## Deployment configuration

Set `GEOSERVER_URL` and `GEOSERVER_WMS_URL` to the browser-facing WMS origin.
Set `GEOSERVER_REST_URL` to a direct/private GeoServer REST origin for worker
uploads; do not point it at a Vercel rewrite or a proxy with a request-body
limit.

`UPLOAD_API_URL` must be the Upload API endpoint used by Tileserver. It is used
to download the artifact into the worker; GeoServer never needs to reach S3 or
local Upload API storage.

The worker verifies `GEOSERVER_WORKSPACE` before publishing. A missing,
unauthorized, or incorrectly routed workspace now fails with a clear error
instead of GeoServer's `WorkspaceInfo.getId()` null-workspace exception.
