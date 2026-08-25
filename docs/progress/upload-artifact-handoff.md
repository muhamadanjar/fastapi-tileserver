Related Plan: [Upload Artifact Handoff Plan](../plans/upload-artifact-handoff.md)

# Upload Artifact Handoff Progress

- [x] Initialize plan and progress documentation.
- [x] Add upload_api client and artifact handoff endpoint.
- [x] Reuse existing geospatial validation and tiling without changing legacy flows.
- [x] Compile-check integration and write final feature documentation.
- [x] Release artifact leases after tiling completes, on exhausted retries, and on early-cancel abort (previously leases were held forever, pinning source artifacts against upload_api cleanup). See tests/test_artifact_lease_release.py.
- [x] Fix cross-service Celery queue collision (2026-08-24): upload_api and tileserver_api both consumed the broker-default `celery` queue, so tileserver workers discarded unknown `upload.*` tasks — artifacts stuck in `verifying`, sessions stuck in `completing`. upload_api now routes `upload.*` to dedicated queue `upload` (worker + dispatcher client); tileserver_api moved to queue `tileserver`.
- [x] upload_api hardening during the same incident: ClamAV scan timeout made configurable (`CLAMAV_TIMEOUT`, default 120s, was hardcoded 30s — 6.5MB zips timed out → permanent `verification_failed`); `verify()` now re-raises `ScannerUnavailableError` until the final attempt so Celery autoretry engages instead of dead-ending the artifact.
- [x] Malware scan kill-switch for dev (2026-08-24): `MALWARE_SCAN_REQUIRED=false` in settings now skips scanning entirely in `verify()` (beats locator snapshots), so development can run without clamd — no scan attempts, no retries, artifacts go straight to `available` with `scan_result="skipped: malware scan disabled"`. See tests/test_verify_scan_kill_switch.py.
- [x] Fix 422 "Invalid access token" on tileserver artifact handoff (2026-08-24): upload_api already had OAuth introspection code but lacked config — added OAUTH_INTROSPECTION_CLIENT_ID/SECRET (client "Upload API", secret rotated via DB) + USERMANAGEMENT_API_URL=:8070 to upload_api/.env; set oauth_clients.introspection_audiences='upload-api' in usermanagement DB. Also fixed latent identity mismatch breaking ALL handoffs: grant consumer 'tileserver' never matched OAuth service_name 'tileserver-api' — aligned dashboard types/transport/callers, upload_api schema Literal, and tests. E2E verified: grant → lease → metadata → release via OAuth.
