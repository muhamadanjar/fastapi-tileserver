# Artifact manual tiling

## Goal

Make artifact and legacy uploads share the same processing flow: both become `uploaded` first, then start tiling only after the user chooses output format and max zoom.

## Implementation

1. The artifact handoff creates an upload session and retains its artifact lease, but does not dispatch Celery.
2. The existing `/uploads/{upload_id}/tile` endpoint accepts the artifact-backed session and dispatches the selected tiling job.
3. A tiling dispatch immediately transitions the session to `processing` to prevent a duplicate request.

Progress: [artifact-manual-tiling](../progress/artifact-manual-tiling.md)
