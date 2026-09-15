"""OpenTelemetry adapter for the standard-library logging system."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any


_OTEL_HANDLER_MARKER = "_fastapi_tileserver_otel_handler"


@dataclass
class OpenTelemetryLogging:
    """Owns the OTEL logger provider and its stdlib logging bridge."""

    provider: Any = None
    handler: logging.Handler | None = None

    @property
    def enabled(self) -> bool:
        return self.provider is not None and self.handler is not None

    def shutdown(self) -> None:
        if self.provider is None:
            return
        try:
            self.provider.shutdown()
        finally:
            if self.handler is not None:
                root_logger = logging.getLogger()
                if self.handler in root_logger.handlers:
                    root_logger.removeHandler(self.handler)
            self.provider = None
            self.handler = None


def configure_otel_logging(*, enabled: bool, service_name: str, endpoint: str | None = None) -> OpenTelemetryLogging:
    """Install the OTEL stdlib bridge when explicitly enabled.

    OTEL setup is best-effort: an unavailable collector or missing optional
    package must never prevent the API from starting.
    """
    if not enabled:
        return OpenTelemetryLogging()

    root_logger = logging.getLogger()
    for existing in root_logger.handlers:
        if getattr(existing, _OTEL_HANDLER_MARKER, False):
            return OpenTelemetryLogging()

    try:
        from opentelemetry import _logs
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({"service.name": service_name})
        provider = LoggerProvider(resource=resource)
        exporter = OTLPLogExporter(endpoint=endpoint) if endpoint else OTLPLogExporter()
        provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
        _logs.set_logger_provider(provider)

        handler = LoggingHandler(level=logging.NOTSET, logger_provider=provider)
        setattr(handler, _OTEL_HANDLER_MARKER, True)
        root_logger.addHandler(handler)
        return OpenTelemetryLogging(provider=provider, handler=handler)
    except Exception:
        logging.getLogger(__name__).warning(
            "OpenTelemetry logging initialization failed; continuing without OTLP export.",
            exc_info=True,
        )
        return OpenTelemetryLogging()
