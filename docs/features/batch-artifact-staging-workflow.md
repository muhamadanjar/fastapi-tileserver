# Batch artifact staging workflow

Related Plan: [Batch artifact staging workflow](../plans/batch-artifact-staging-workflow.md)
Progress Archive: [batch-artifact-staging-workflow](../progress/batch-artifact-staging-workflow.md)

`POST /api/v1/uploads/artifact` supports two explicit workflows:

- `workflow: "layer"` (the compatibility default) stages a single-layer source
  and retains `raster` as its default output when no format is supplied.
- `workflow: "batch"` stages a ZIP only for `POST /batches/inspect`. It cannot
  carry `output_format`; its stored value is `staged` and is never used as a
  batch rendering decision.

For a Multi-SHP ZIP, the only output decision is made after inspection through
`POST /batches/{id}/configure`, with one of `raster`, `mvt`, or `wms`. This
endpoint is also the only step that queues the batch processing worker.
