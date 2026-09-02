# Field Sync Artifact Lease

Related Plan: [Field Sync Artifact Lease Plan](../plans/field-sync-artifact-lease.md)  
Related Progress: [Field Sync Artifact Lease Progress](../progress/field-sync-artifact-lease.md)

Field Settings and Get Info can read an artifact-backed layer after its original
processing lease has been released. The `GET /api/v1/layers/{layer_id}/fields` and
`GET /api/v1/layers/{layer_id}/features` requests forward the editor's bearer token
to their use cases.

If the source artifact is not already cached and its processing lease is no
longer active, Tile Server uses that bearer token to ask Upload API for a fresh
grant for `tileserver-api`. It then acquires a temporary lease with its service
credentials, copies the source into `ARTIFACT_CACHE_DIR`, and releases the
temporary lease. Later synchronizations use the cached source and do not need a
new grant.

The editor must retain its normal `Authorization: Bearer <token>` header when
calling either endpoint. No client-side artifact identifier or grant handling is
required.
