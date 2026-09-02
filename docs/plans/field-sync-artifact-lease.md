# Field Sync Artifact Lease Plan

Related Progress: [Field Sync Artifact Lease Progress](../progress/field-sync-artifact-lease.md)
Related Feature: [Field Sync Artifact Lease](../features/field-sync-artifact-lease.md)

Allow Field Settings synchronization and Get Info queries to read artifact-backed
layer sources after the processing lease has been released. Each endpoint will use
the caller's bearer token to request a short-lived upload_api grant, acquire a
temporary service lease, materialize the source into the existing cache, then
release that temporary lease.

The legacy source-path and already-cached artifact paths remain unchanged.
