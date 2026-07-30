"""OpenTelemetry setup and helpers for HTTP, database, and pipeline traces."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_provider: Any | None = None

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

    OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover - minimal local installs
    OTEL_AVAILABLE = False


def configure_tracing(app: Any) -> None:
    """Configure the exporter and instrument FastAPI plus SQLAlchemy."""
    global _provider
    settings = get_settings()
    if not settings.tracing_enabled or not OTEL_AVAILABLE:
        if settings.tracing_enabled and not OTEL_AVAILABLE:
            logger.warning("tracing_dependencies_missing")
        return

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.tracing_service_name,
                "service.version": app.version,
                "deployment.environment": settings.environment.value,
            }
        ),
        sampler=TraceIdRatioBased(settings.tracing_sample_rate),
    )
    if settings.tracing_otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.tracing_otlp_endpoint))
            )
            logger.info("tracing_configured", exporter="otlp_http")
        except ImportError:
            logger.warning("otlp_exporter_dependency_missing")
    elif settings.debug:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        logger.info("tracing_configured", exporter="console")
    else:
        logger.info("tracing_configured", exporter="none", reason="no OTLP endpoint")

    trace.set_tracer_provider(provider)
    _provider = provider
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    except ImportError:
        logger.warning("fastapi_instrumentation_dependency_missing")
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        from app.core.database import engine

        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine, tracer_provider=provider)
    except ImportError:
        logger.warning("sqlalchemy_instrumentation_dependency_missing")


def get_tracer(name: str = "invoice-intelligence"):
    """Return the configured tracer or a no-op tracer."""
    if OTEL_AVAILABLE:
        return trace.get_tracer(name)

    class NoopTracer:
        @contextmanager
        def start_as_current_span(self, *_args, **_kwargs):
            yield NoopSpan()

    return NoopTracer()


class NoopSpan:
    def set_attribute(self, *_args, **_kwargs):
        return None

    def record_exception(self, *_args, **_kwargs):
        return None

    def set_status(self, *_args, **_kwargs):
        return None


@contextmanager
def stage_span(name: str, **attributes: Any):
    """Create a span with common attributes and error status handling."""
    with get_tracer().start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            if OTEL_AVAILABLE:
                from opentelemetry.trace import Status, StatusCode

                span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def shutdown_tracing() -> None:
    """Flush pending spans during graceful shutdown."""
    if _provider is not None:
        _provider.force_flush(timeout_millis=5000)
        _provider.shutdown()
