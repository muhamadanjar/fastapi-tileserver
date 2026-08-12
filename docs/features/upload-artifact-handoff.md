# Upload Artifact Handoff

Related Plan: [Upload Artifact Handoff Plan](../plans/upload-artifact-handoff.md)

Related Progress: [Upload Artifact Handoff Progress](../progress/upload-artifact-handoff.md)

`POST /api/v1/uploads/artifact` creates a tiling job from an available upload_api artifact. Requests include `artifact_id`, one-time `grant_id`, stable `handoff_id`, `output_format`, and optional `max_zoom`.

Tileserver exchanges the grant for an Artifact Lease and stores only `artifact_id`, `artifact_lease_id`, `artifact_handoff_id`, and an `artifact://` source reference. The worker downloads an ephemeral source copy, uses the existing archive preparation and tiling pipeline, and removes the copy afterward.

The stable handoff ID makes dashboard retries idempotent. Dispatch failure deletes the partial upload-session record and releases the lease as compensation. Existing direct and chunked upload routes remain unchanged for legacy sessions.

Configure:

```env
UPLOAD_API_URL=http://upload-api:8010/api/v1
UPLOAD_API_CALLER_TOKEN=<tileserver-specific-upload-api-caller-token>
```

The caller token must equal the `tileserver` entry in Upload API's `UPLOAD_API_TRUSTED_SERVICE_TOKENS` map. `UPLOAD_API_SERVICE_TOKEN` remains a deprecated fallback during migration.

Apply migration `0006_add_upload_artifact_reference` before enabling the dashboard cutover.
