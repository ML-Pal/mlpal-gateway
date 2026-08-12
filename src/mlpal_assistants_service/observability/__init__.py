"""Observability package for metrics, tracing, and logging."""

from mlpal_assistants_service.observability.middleware import (
    ObservabilityMiddleware,
)

__all__ = ["ObservabilityMiddleware"]
