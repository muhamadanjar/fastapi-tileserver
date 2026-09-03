Related Plan: [Artifact manual tiling](../plans/artifact-manual-tiling.md)

# Progress

- [x] Confirm the desired artifact and legacy process contract.
- [x] Change artifact handoff to stage rather than dispatch tiling.
- [x] Verify targeted TileServer tests and Python compilation.
- [x] Add cooperative cancellation to the tiling task: `process_tiling_task` now checks the upload session's `JobStatus` in the progress callback and aborts (`TilingCancelled`) when the cancel endpoint flips it to `cancelled`, releasing the artifact lease and skipping retries.
- [x] Surface the cancel action in the dashboard UI: `useCancelTiling` + `cancelTiling` API call, and a "Cancel tiling" button in `processing-choice-dialog.tsx` that hits `POST /uploads/{id}/cancel` and resets the dialog when the job reports `cancelled`.

Feature documentation: [Artifact manual tiling](../features/artifact-manual-tiling.md)
