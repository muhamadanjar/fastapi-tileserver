# OpenTelemetry Logging

Related Progress: [OpenTelemetry Logging Progress](../progress/opentelemetry-logging.md)

## Objective

Add OpenTelemetry SDK log export to FastAPI TileServer while preserving existing Python logging behavior. Logs must be exported through OTLP when enabled and remain locally available when telemetry is disabled or unavailable.

## Architecture

- `app/infrastructure/observability/`: OpenTelemetry adapter and lifecycle.
- `app/core/config.py`: environment-driven telemetry settings only.
- `app/main.py`: application startup/shutdown wiring; no exporter details in presentation.
- Existing `logging.Logger` call sites remain unchanged.

## Decisions

- Use the OpenTelemetry Logs SDK `LoggingHandler` as the bridge from standard-library logging.
- Use OTLP over gRPC exporter, configured through standard OpenTelemetry environment variables.
- Make export opt-in with `OTEL_ENABLED=false` by default to preserve local behavior.
- Fail gracefully on exporter initialization failure; application startup must not fail because an observability backend is unavailable.
- Shut down the provider during application shutdown to flush batched records.
- Never log exporter headers or credentials.

## Acceptance Criteria

- [x] Dependencies are pinned in the runtime requirements.
- [x] Settings expose enablement and service name without secrets.
- [x] Existing Python logs are bridged to OTEL when enabled.
- [x] Disabled mode adds no OTEL handler.
- [x] Initialization/exporter errors do not prevent application startup.
- [x] Provider shutdown is idempotent and flushes pending records.
- [x] Unit tests cover enabled, disabled, failure, and shutdown behavior.
- [x] Focused observability tests pass; full suite requires the project's complete dependency set.
- [x] No commit or push is performed.

## Verification

- `python3 -m compileall -q app tests`
- focused observability unit tests
- full `pytest` if project dependencies are available
- `git diff --check`
