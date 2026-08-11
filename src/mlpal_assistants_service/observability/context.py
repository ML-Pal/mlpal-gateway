"""Trace context utilities.

Provides utilities for working with trace context:
- Getting current trace/span IDs
- Injecting trace context into logs
- Creating child spans
"""

from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode


def get_trace_id() -> str | None:
    """Get current trace ID as hex string."""
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        return format(span.get_span_context().trace_id, "032x")
    return None


def get_span_id() -> str | None:
    """Get current span ID as hex string."""
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        return format(span.get_span_context().span_id, "016x")
    return None


def get_current_span() -> Span | None:
    """Get the current active span."""
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        return span
    return None


def set_span_attributes(attributes: dict[str, Any]) -> None:
    """Set attributes on the current span."""
    span = get_current_span()
    if span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)


def set_span_error(error: Exception, message: str | None = None) -> None:
    """Mark current span as error with exception info."""
    span = get_current_span()
    if span:
        span.set_status(Status(StatusCode.ERROR, message or str(error)))
        span.record_exception(error)


def add_span_event(name: str, attributes: dict[str, Any] | None = None) -> None:
    """Add an event to the current span."""
    span = get_current_span()
    if span:
        span.add_event(name, attributes=attributes or {})


def create_tracer(name: str) -> trace.Tracer:
    """Create a tracer for a specific module/component."""
    return trace.get_tracer(name)


# Pre-configured tracers for common components
def get_api_tracer() -> trace.Tracer:
    """Get tracer for API layer."""
    return create_tracer("mlpal.assistants.api")


def get_service_tracer() -> trace.Tracer:
    """Get tracer for service layer."""
    return create_tracer("mlpal.assistants.service")


def get_adapter_tracer() -> trace.Tracer:
    """Get tracer for adapter layer."""
    return create_tracer("mlpal.assistants.adapter")


def get_db_tracer() -> trace.Tracer:
    """Get tracer for database layer."""
    return create_tracer("mlpal.assistants.db")
