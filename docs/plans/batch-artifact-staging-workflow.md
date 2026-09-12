# Batch artifact staging workflow

Status: active

Related Progress: [batch-artifact-staging-workflow](../progress/batch-artifact-staging-workflow.md)

## Goal

Make the artifact handoff explicitly distinguish a staged Multi-SHP batch from a
single-layer tiling job. A staged batch must not carry a raster/MVT output
decision; `POST /batches/{id}/configure` remains the only place that selects
`raster`, `mvt`, or `wms` and starts processing.

## Plan

1. Add an explicit `workflow` discriminator to the artifact handoff contract.
2. Persist `staged` for batch handoffs so legacy layer processing still retains
   its raster default without being interpreted as the batch output.
3. Reject a batch handoff that also supplies an output format.
4. Update the backoffice batch client and the affected documentation.
5. Cover the resolution rules with focused tests and run the relevant suite.
