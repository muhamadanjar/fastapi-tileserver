# Clean Architecture & DDD Hardening

[Plan](../plans/clean-architecture-ddd-hardening.md) · [Progress](../progress/clean-architecture-ddd-hardening.md)

## Dependency direction

`app/domain`, `app/application`, `app/usecases`, and `app/analysis` are inner
layers. They do not import `app.infrastructure`, `app.presentation`, or
`app.workers`. Their dependencies are declared as domain ports and injected by
API endpoints or worker entry points.

Concrete adapters (database repositories, artifact clients, Nominatim, chunk
storage, legend rendering, reference-source loading, and task enqueueing) are
created in the outer layer and passed into use cases. This makes the use cases
testable with fakes and prevents framework-specific adapter dependencies from
leaking inward.

## Reference analysis

The API and Celery worker construct `ReferenceAnalysis` with a
`ReferenceSourcePort` and `AnalysisStoragePort`. The requested operation is
validated, persisted on the job, and executed by the worker. The rows endpoint
delegates result reading to the application service through its storage port.

Saving a finished job creates one durable, active GeoJSON layer and upload
record. The application module uses deterministic IDs, so retrying
`POST /analysis-workspace/jobs/{job_id}/save` returns the same layer instead of
duplicating either the catalogue entry or the result file. The durable copy is
made through `AnalysisStoragePort`, keeping filesystem details in the
infrastructure adapter.

## Keeping the boundary intact

Run the architecture guard together with the relevant feature tests:

```sh
pytest -q tests/test_architecture_boundaries.py tests/test_reference_analysis.py
```

When adding a dependency, define or extend a domain port, implement it under
`app/infrastructure`, and inject it from presentation or worker composition.
