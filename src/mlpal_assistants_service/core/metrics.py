"""Metrics emission using AWS EMF (Embedded Metrics Format).

Supports two modes:
- Local: Prints metrics as JSON to stdout (for debugging)
- AWS: Emits EMF-formatted logs that CloudWatch parses into metrics

Configuration:
    METRICS_ENABLED: Enable/disable metrics (default: true)
    AWS_EMF_NAMESPACE: CloudWatch metrics namespace (default: MLPal/Assistants)
    ENVIRONMENT: local uses stdout, others use EMF
"""

import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from mlpal_assistants_service.core.config import get_settings

logger = logging.getLogger(__name__)

# Try to import EMF library, fallback to console if not available
try:
    from aws_embedded_metrics import metric_scope
    from aws_embedded_metrics.config import get_config
    from aws_embedded_metrics.logger.metrics_logger import MetricsLogger

    EMF_AVAILABLE = True
except ImportError:
    EMF_AVAILABLE = False
    metric_scope = None
    MetricsLogger = None


class MetricsEmitter:
    """
    Metrics emitter that works in both local and AWS environments.

    Local: Logs metrics as structured JSON
    AWS: Uses EMF format for CloudWatch metrics
    """

    def __init__(self):
        self.settings = get_settings()
        self.enabled = self.settings.metrics_enabled
        self.namespace = self.settings.metrics_namespace
        # Only use console mode when explicitly running locally (not in k8s/AWS)
        # Check for "local" environment or missing EMF library
        self.is_local = self.settings.environment == "local"

        if self.enabled and EMF_AVAILABLE and not self.is_local:
            # Configure EMF
            config = get_config()
            config.namespace = self.namespace
            config.service_name = self.settings.otel_service_name
            logger.info(f"EMF metrics enabled, namespace: {self.namespace}")
        elif self.enabled:
            logger.info("Console metrics enabled (local mode or EMF not available)")

    def _emit_console(
        self,
        metric_name: str,
        value: float,
        unit: str,
        dimensions: dict[str, str],
    ) -> None:
        """Emit metric to console as JSON (for local development)."""
        metric_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metric": metric_name,
            "value": value,
            "unit": unit,
            "namespace": self.namespace,
            "dimensions": dimensions,
        }
        # Use a specific prefix so we can filter these in logs
        print(f"METRIC: {json.dumps(metric_data)}")

    async def put_metric(
        self,
        name: str,
        value: float,
        unit: str = "Count",
        dimensions: dict[str, str] | None = None,
    ) -> None:
        """
        Emit a single metric.

        Args:
            name: Metric name (e.g., "RequestCount")
            value: Metric value
            unit: CloudWatch unit (Count, Milliseconds, Bytes, etc.)
            dimensions: Metric dimensions (e.g., {"model": "gpt-5.2"})
        """
        if not self.enabled:
            return

        dims = dimensions or {}

        if self.is_local or not EMF_AVAILABLE:
            self._emit_console(name, value, unit, dims)
            return

        # Use EMF for AWS
        @metric_scope
        async def emit(metrics: MetricsLogger):
            for dim_name, dim_value in dims.items():
                metrics.set_dimensions({dim_name: dim_value})
            metrics.put_metric(name, value, unit)

        await emit()

    def put_metric_sync(
        self,
        name: str,
        value: float,
        unit: str = "Count",
        dimensions: dict[str, str] | None = None,
    ) -> None:
        """Synchronous version of put_metric for use in non-async contexts."""
        if not self.enabled:
            return

        dims = dimensions or {}

        if self.is_local or not EMF_AVAILABLE:
            self._emit_console(name, value, unit, dims)
            return

        # For sync contexts in AWS, just log as EMF JSON
        # This will be picked up by CloudWatch Logs
        emf_log = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": self.namespace,
                        "Dimensions": [list(dims.keys())] if dims else [[]],
                        "Metrics": [{"Name": name, "Unit": unit}],
                    }
                ],
            },
            name: value,
            **dims,
        }
        print(json.dumps(emf_log))

    @contextmanager
    def measure_latency(
        self,
        metric_name: str,
        dimensions: dict[str, str] | None = None,
    ):
        """
        Context manager to measure and emit latency.

        Usage:
            with metrics.measure_latency("ProviderLatency", {"provider": "openai"}):
                await provider.call()
        """
        start_time = time.perf_counter()
        try:
            yield
        finally:
            latency_ms = (time.perf_counter() - start_time) * 1000
            self.put_metric_sync(
                metric_name,
                latency_ms,
                unit="Milliseconds",
                dimensions=dimensions,
            )


# Global metrics emitter instance
_metrics_emitter: MetricsEmitter | None = None


def get_metrics() -> MetricsEmitter:
    """Get the global metrics emitter instance."""
    global _metrics_emitter
    if _metrics_emitter is None:
        _metrics_emitter = MetricsEmitter()
    return _metrics_emitter


# Convenience functions for common metrics
async def emit_request_metric(
    operation: str,
    model: str,
    status: str,
    latency_ms: float,
) -> None:
    """Emit request metrics."""
    metrics = get_metrics()
    dimensions = {"operation": operation, "model": model, "status": status}

    await metrics.put_metric("RequestCount", 1, "Count", dimensions)
    await metrics.put_metric("RequestLatency", latency_ms, "Milliseconds", dimensions)


async def emit_provider_metric(
    provider: str,
    model: str,
    latency_ms: float,
    success: bool = True,
) -> None:
    """Emit provider call metrics."""
    metrics = get_metrics()
    dimensions = {"provider": provider, "model": model}

    await metrics.put_metric("ProviderLatency", latency_ms, "Milliseconds", dimensions)
    if not success:
        await metrics.put_metric("ProviderError", 1, "Count", dimensions)


async def emit_token_metric(
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Emit token usage metrics."""
    metrics = get_metrics()

    await metrics.put_metric(
        "InputTokens",
        input_tokens,
        "Count",
        {"model": model, "provider": provider},
    )
    await metrics.put_metric(
        "OutputTokens",
        output_tokens,
        "Count",
        {"model": model, "provider": provider},
    )
    await metrics.put_metric(
        "TotalTokens",
        input_tokens + output_tokens,
        "Count",
        {"model": model, "provider": provider},
    )


async def emit_compute_units_metric(
    model: str,
    provider: str,
    compute_units: float,
) -> None:
    """Emit compute units usage metrics."""
    metrics = get_metrics()
    await metrics.put_metric(
        "ComputeUnits",
        compute_units,
        "Count",
        {"model": model, "provider": provider},
    )


async def emit_rate_limit_metric(tier: str) -> None:
    """Emit rate limit hit metric."""
    metrics = get_metrics()
    await metrics.put_metric(
        "RateLimitHit",
        1,
        "Count",
        {"tier": tier},
    )


async def emit_circuit_breaker_metric(provider: str) -> None:
    """Emit circuit breaker trip metric."""
    metrics = get_metrics()
    await metrics.put_metric(
        "CircuitBreakerTrip",
        1,
        "Count",
        {"provider": provider},
    )
