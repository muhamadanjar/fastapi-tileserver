# GeoServer Artifact Pull URL

Progress: [geoserver-artifact-pull-url](../progress/geoserver-artifact-pull-url.md)
Feature documentation: [GeoServer Artifact Pull URL](../features/geoserver-artifact-pull-url.md)

## Goal

Let a GeoServer worker publish an artifact by downloading it from Upload API
first and then sending the ZIP bytes to GeoServer. The flow must work whether
Upload API stores the artifact on local disk or S3-compatible storage.

## Design

1. Upload API serves the available, leased artifact to the Tileserver worker.
2. Tileserver materializes the artifact and sends its ZIP bytes to GeoServer
   REST `file.shp`.
3. `GEOSERVER_REST_URL` can point to a private/origin listener so the large
   request does not pass through a browser or Vercel proxy.
4. The artifact lease remains held until the publish task succeeds or reaches
   its terminal failure path.

## Verification

- Unit-test both URL flows and error handling in Upload API.
- Unit-test Tileserver's new client method and GeoServer URL publishing call.
- Run focused tests in both services and their relevant static checks.
