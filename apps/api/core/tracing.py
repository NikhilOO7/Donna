"""
OpenTelemetry tracing configuration.

Auto-instruments FastAPI and provides helpers for manual spans.
Tracing is disabled by default; enable via ENABLE_TRACING=true.
"""

import logging

from apps.api.core.config import settings

logger = logging.getLogger(__name__)

_tracer_provider = None


def configure_tracing(app) -> None:
    """Configure OpenTelemetry tracing for the FastAPI application.

    No-op when ``settings.enable_tracing`` is False.
    """
    global _tracer_provider

    if not settings.enable_tracing:
        logger.info("OpenTelemetry tracing disabled (ENABLE_TRACING=false)")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": settings.app_name,
                "service.version": settings.app_version,
                "deployment.environment": settings.environment,
            }
        )

        _tracer_provider = TracerProvider(resource=resource)

        # OTLP exporter (gRPC)
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=settings.otlp_endpoint, insecure=True)
            _tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info(f"OTLP exporter configured: {settings.otlp_endpoint}")
        except Exception as e:
            logger.warning(f"OTLP exporter unavailable, using console: {e}")
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter

            _tracer_provider.add_span_processor(
                BatchSpanProcessor(ConsoleSpanExporter())
            )

        trace.set_tracer_provider(_tracer_provider)

        # Auto-instrument FastAPI
        FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry tracing enabled")

    except ImportError:
        logger.warning(
            "OpenTelemetry packages not installed; tracing disabled. "
            "Install: pip install opentelemetry-instrumentation-fastapi opentelemetry-exporter-otlp"
        )
    except Exception as e:
        logger.error(f"Failed to configure tracing: {e}")


def get_tracer(name: str):
    """Get a tracer instance for manual span creation.

    Returns a no-op tracer when tracing is disabled.
    """
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except ImportError:
        return None
