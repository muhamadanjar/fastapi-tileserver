import logging
import sys
import types
import unittest
from unittest.mock import patch

from app.infrastructure.observability.otel_logging import configure_otel_logging


class OpenTelemetryLoggingTests(unittest.TestCase):
    def tearDown(self):
        root = logging.getLogger()
        for handler in list(root.handlers):
            if getattr(handler, "_fastapi_tileserver_otel_handler", False):
                root.removeHandler(handler)

    def test_disabled_does_not_install_handler(self):
        result = configure_otel_logging(enabled=False, service_name="test")
        self.assertFalse(result.enabled)

    def test_missing_sdk_fails_open(self):
        with patch.dict(sys.modules, {"opentelemetry": None}):
            result = configure_otel_logging(enabled=True, service_name="test")
        self.assertFalse(result.enabled)

    def test_shutdown_without_provider_is_idempotent(self):
        result = configure_otel_logging(enabled=False, service_name="test")
        result.shutdown()
        result.shutdown()
        self.assertFalse(result.enabled)

    def test_enabled_installs_bridge_with_fake_sdk(self):
        class FakeProvider:
            def __init__(self, resource):
                self.resource = resource
                self.processors = []
                self.shutdown_called = False

            def add_log_record_processor(self, processor):
                self.processors.append(processor)

            def shutdown(self):
                self.shutdown_called = True

        class FakeHandler(logging.Handler):
            def __init__(self, level, logger_provider):
                super().__init__(level)
                self.logger_provider = logger_provider

        fake_logs = types.SimpleNamespace(set_logger_provider=lambda provider: None)
        fake_exporter = types.SimpleNamespace(OTLPLogExporter=lambda endpoint=None: object())
        fake_sdk_logs = types.SimpleNamespace(LoggerProvider=FakeProvider, LoggingHandler=FakeHandler)
        fake_sdk_export = types.SimpleNamespace(BatchLogRecordProcessor=lambda exporter: exporter)
        fake_resources = types.SimpleNamespace(Resource=types.SimpleNamespace(create=lambda value: value))
        modules = {
            "opentelemetry": types.SimpleNamespace(_logs=fake_logs),
            "opentelemetry.exporter": types.ModuleType("opentelemetry.exporter"),
            "opentelemetry.exporter.otlp": types.ModuleType("opentelemetry.exporter.otlp"),
            "opentelemetry.exporter.otlp.proto": types.ModuleType("opentelemetry.exporter.otlp.proto"),
            "opentelemetry.exporter.otlp.proto.grpc": types.ModuleType("opentelemetry.exporter.otlp.proto.grpc"),
            "opentelemetry.exporter.otlp.proto.grpc._log_exporter": fake_exporter,
            "opentelemetry.sdk": types.ModuleType("opentelemetry.sdk"),
            "opentelemetry.sdk._logs": fake_sdk_logs,
            "opentelemetry.sdk._logs.export": fake_sdk_export,
            "opentelemetry.sdk.resources": fake_resources,
        }
        with patch.dict(sys.modules, modules):
            result = configure_otel_logging(enabled=True, service_name="test", endpoint="http://collector:4317")
        self.assertTrue(result.enabled)
        self.assertEqual(result.provider.resource, {"service.name": "test"})
        result.shutdown()
        self.assertFalse(result.enabled)


if __name__ == "__main__":
    unittest.main()
