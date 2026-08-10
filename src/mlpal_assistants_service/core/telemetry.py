"""OpenTelemetry tracing setup.

Supports two environments:
- Local: OTLP exporter to Jaeger (http://localhost:4317)
- AWS: OTLP exporter to ADOT sidecar → X-Ray

Configuration:
    TRACING_ENABLED: Enable/disable tracing (default: true)
    OTEL_EXPORTER_OTLP_ENDPOINT: OTLP endpoint (default: http://localhost:4317)
    OTEL_SERVICE_NAME: Service name (default: mlpal-assistants-service)
    ENVIRONMENT: local/dev/prod (affects propagator selection)
"""

import logging
from functools import lru_cache

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from mlpal_assistants_service.core.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_resource() -> Resource:
    """Create OpenTelemetry resource with service metadata."""
    settings = get_settings()

    return Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": settings.app_version,
            "deployment.environment": settings.environment,
            "cloud.provider": "aws",
            "cloud.region": settings.aws_region,
        }
    )


def setup_tracing(debug: bool = False) -> TracerProvider | None:
    """
    Initialize OpenTelemetry tracing.

    Args:
        debug: If True, use SimpleSpanProcessor (immediate export) for debugging.
               If False, use BatchSpanProcessor (production).

    Returns:
        TracerProvider if tracing is enabled, None otherwise.
    """
    settings = get_settings()

    if not settings.tracing_enabled:
        logger.info("Tracing is disabled")
        return None

    logger.info(
        "Initializing tracing",
        extra={
            "endpoint": settings.otel_exporter_endpoint,
            "service": settings.otel_service_name,
            "environment": settings.environment,
        },
    )

    # Create tracer provider with resource
    resource = get_resource()
    provider = TracerProvider(resource=resource)

    # Create OTLP exporter
    exporter = OTLPSpanExporter(
        endpoint=settings.otel_exporter_endpoint,
        insecure=True,  # Local/sidecar doesn't need TLS
    )

    # Use SimpleSpanProcessor for debugging, BatchSpanProcessor for production
    if debug or settings.otel_debug:
        processor = SimpleSpanProcessor(exporter)
        logger.info("Using SimpleSpanProcessor (debug mode)")
    else:
        processor = BatchSpanProcessor(
            exporter,
            max_queue_size=2048,
            max_export_batch_size=512,
            schedule_delay_millis=5000,
        )
        logger.info("Using BatchSpanProcessor (production mode)")

    provider.add_span_processor(processor)

    # Set as global tracer provider
    trace.set_tracer_provider(provider)

    # Set up propagators
    # In AWS with X-Ray, the ADOT collector handles X-Ray propagation
    # We use W3C TraceContext for compatibility
    propagators = [TraceContextTextMapPropagator()]

    # If in AWS environment, also add X-Ray propagator
    if settings.environment in ("production", "staging"):
        try:
            from opentelemetry.propagators.aws import AwsXRayPropagator

            propagators.append(AwsXRayPropagator())
            logger.info("Added AWS X-Ray propagator")
        except ImportError:
            logger.warning("AWS X-Ray propagator not available")

    set_global_textmap(CompositePropagator(propagators))

    logger.info("Tracing initialized successfully")
    return provider


def instrument_app(app, engine=None) -> None:
    """
    Instrument the FastAPI application and its dependencies.

    Args:
        app: FastAPI application instance
        engine: SQLAlchemy engine instance (optional)
    """
    settings = get_settings()

    if not settings.tracing_enabled:
        return

    # Instrument FastAPI
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="health,health/ready,health/live,docs,redoc,openapi.json",
    )
    logger.info("Instrumented FastAPI")

    # Instrument SQLAlchemy
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(
            engine=engine.sync_engine,
            enable_commenter=True,
            commenter_options={
                "db_driver": True,
                "db_framework": True,
                "opentelemetry_values": True,
            },
        )
        logger.info("Instrumented SQLAlchemy")

    # Instrument Redis
    RedisInstrumentor().instrument()
    logger.info("Instrumented Redis")

    # Instrument httpx (used by AI provider SDKs)
    HTTPXClientInstrumentor().instrument()
    logger.info("Instrumented httpx")

    # Instrument logging to add trace context
    LoggingInstrumentor().instrument(
        set_logging_format=False,  # We handle our own format
        log_level=logging.INFO,
    )
    logger.info("Instrumented logging")


def shutdown_tracing() -> None:
    """Shutdown tracing and flush pending spans."""
    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush(timeout_millis=5000)
        logger.info("Flushed pending spans")
    if hasattr(provider, "shutdown"):
        provider.shutdown()
        logger.info("Tracing shutdown complete")


def get_tracer(name: str = __name__):
    """Get a tracer instance for creating spans."""
    return trace.get_tracer(name)


def get_current_span():
    """Get the current active span."""
    return trace.get_current_span()


def get_trace_id() -> str | None:
    """Get the current trace ID as a hex string."""
    span = get_current_span()
    if span and span.get_span_context().is_valid:
        return format(span.get_span_context().trace_id, "032x")
    return None
