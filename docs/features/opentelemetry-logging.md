# OpenTelemetry Logging

Related Plan: [OpenTelemetry Logging Plan](../plans/opentelemetry-logging.md)

## What it does

The TileServer keeps using Python's standard `logging` API. During FastAPI startup, `app.infrastructure.observability.otel_logging` installs the OpenTelemetry `LoggingHandler` on the root logger when `OTEL_ENABLED=true`. The OTLP gRPC exporter batches log records and exports them to the configured collector.

Startup is fail-open: if the SDK/exporter cannot initialize, the API continues with normal local logging. During shutdown the provider is flushed/shut down and the bridge handler is removed.

## Configuration

Set these environment variables in the deployment secret/config environment:

```dotenv
OTEL_ENABLED=true
OTEL_SERVICE_NAME=fastapi-tileserver
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

The default is `OTEL_ENABLED=false`, so existing local and production behavior is preserved until explicitly enabled. Use standard OTEL exporter environment variables for authentication/headers; do not put credentials in source code or logs.

## Files

- `app/core/config.py`: telemetry settings.
- `app/infrastructure/observability/otel_logging.py`: OTEL SDK adapter.
- `app/main.py`: startup/shutdown lifecycle wiring.
- `requirements.txt`: pinned OTEL SDK/API/OTLP gRPC dependencies.
- `tests/test_otel_logging.py`: focused behavior tests.

## Verification

Focused tests cover disabled mode, missing-SDK fail-open behavior, real handler lifecycle with a fake SDK boundary, and idempotent shutdown. The installed SDK was also initialized and shut down successfully against a local test endpoint without requiring a collector.

## Related history

- [Plan](../plans/opentelemetry-logging.md)
- [Progress](../progress/opentelemetry-logging.md)
