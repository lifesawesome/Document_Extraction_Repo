"""Telemetry — OpenTelemetry instrumentation with Azure Monitor exporter.

Provides structured event tracking, custom metrics, and exception recording
across all pipeline stages. Integrates with Application Insights for dashboards,
alerting, and distributed tracing.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Optional imports — telemetry degrades gracefully if not installed
try:
    from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource
    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False


class Telemetry:
    """Structured telemetry for pipeline observability.

    Tracks:
    - Pipeline stage transitions (events with properties)
    - Custom metrics (fill_rate, confidence, duration)
    - Exceptions with context
    - Distributed traces across stages

    Degrades gracefully: if OpenTelemetry is not installed or no connection
    string is provided, falls back to standard logging.
    """

    def __init__(self, connection_string: Optional[str] = None):
        self._tracer = None

        if _OTEL_AVAILABLE and connection_string:
            try:
                resource = Resource.create({"service.name": "document-extraction-pipeline"})
                provider = TracerProvider(resource=resource)

                exporter = AzureMonitorTraceExporter(connection_string=connection_string)
                provider.add_span_processor(BatchSpanProcessor(exporter))

                trace.set_tracer_provider(provider)
                self._tracer = trace.get_tracer("document_extraction")

                logger.info("Telemetry: OpenTelemetry initialized with Azure Monitor")
            except Exception as e:
                logger.warning("Telemetry: failed to initialize OpenTelemetry: %s", e)
        else:
            logger.info("Telemetry: running in log-only mode (no Application Insights)")

    # ------------------------------------------------------------------
    # Event tracking
    # ------------------------------------------------------------------
    def track_event(self, name: str, properties: Optional[Dict[str, str]] = None) -> None:
        """Track a named event with optional properties.

        Events are used for pipeline stage transitions, decisions, and milestones.
        """
        props = properties or {}

        if self._tracer:
            with self._tracer.start_as_current_span(name) as span:
                for key, value in props.items():
                    span.set_attribute(f"custom.{key}", value)
        else:
            logger.info("Event: %s | %s", name, props)

    # ------------------------------------------------------------------
    # Exception tracking
    # ------------------------------------------------------------------
    def track_exception(self, exception: Exception, properties: Optional[Dict[str, str]] = None) -> None:
        """Record an exception with context for debugging."""
        props = properties or {}

        if self._tracer:
            span = trace.get_current_span()
            if span:
                span.record_exception(exception)
                for key, value in props.items():
                    span.set_attribute(f"custom.{key}", value)
        else:
            logger.exception("Exception tracked: %s | %s", exception, props)

    # ------------------------------------------------------------------
    # Metrics (simplified — extend with OpenTelemetry metrics SDK for production)
    # ------------------------------------------------------------------
    def track_metric(self, name: str, value: float, properties: Optional[Dict[str, str]] = None) -> None:
        """Track a custom metric value.

        For production, integrate with OpenTelemetry Metrics SDK:
        - Histogram for durations and distributions
        - Counter for event counts
        - Gauge for current state values
        """
        props = properties or {}

        if self._tracer:
            with self._tracer.start_as_current_span(f"metric.{name}") as span:
                span.set_attribute("metric.name", name)
                span.set_attribute("metric.value", value)
                for key, val in props.items():
                    span.set_attribute(f"custom.{key}", val)
        else:
            logger.info("Metric: %s=%.4f | %s", name, value, props)
