# Retile Maximum Zoom

Related Plan: [Retile Maximum Zoom Plan](../plans/retile-max-zoom.md)  
Related Progress: [Retile Maximum Zoom Progress](../progress/retile-max-zoom.md)

`POST /api/v1/layers/{layer_id}/retile?max_zoom={0..22}` regenerates a local SHP/vector
or raster tile pyramid to the requested maximum zoom. TileServer records that value in
the upload session before the worker runs, so later status and retries retain it.

For an `artifact://` source (including Upload API deployments backed by S3), the
endpoint forwards the editor bearer token to create a fresh grant and temporary lease.
The worker materializes through Upload API rather than accessing S3 directly, and
releases the lease once tiling succeeds or its retries are exhausted. Local legacy
TileServer paths remain unchanged.
