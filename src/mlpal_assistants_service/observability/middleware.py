"""Request metrics middleware for FastAPI.

Collects metrics for all HTTP requests:
- Request count by operation, model, status
- Request latency by operation, model
"""

import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from mlpal_assistants_service.core.metrics import get_metrics


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware to collect request metrics."""

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.metrics = get_metrics()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process request and emit metrics."""
        # Never enter the metrics path for CORS preflights — they carry no
        # operation/model and must round-trip fast. (With CORS as the outermost
        # layer this middleware shouldn't see them anyway; this is defensive.)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Skip metrics for health endpoints
        path = request.url.path
        if path.startswith("/health") or path in ("/", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        start_time = time.perf_counter()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            latency_ms = (time.perf_counter() - start_time) * 1000

            # Extract operation from path
            operation = self._extract_operation(path)

            # Extract model from request body if available (cached by FastAPI)
            model = getattr(request.state, "model", "unknown")

            # Categorize status
            status = self._categorize_status(status_code)

            # Emit metrics
            dimensions = {
                "operation": operation,
                "model": model,
                "status": status,
            }

            self.metrics.put_metric_sync("RequestCount", 1, "Count", dimensions)
            self.metrics.put_metric_sync(
                "RequestLatency", latency_ms, "Milliseconds", dimensions
            )

    def _extract_operation(self, path: str) -> str:
        """Extract operation name from request path."""
        # /v1/chat/completions -> chat_completions
        # /v1/embeddings -> embeddings
        # /v1/images/generations -> image_generations
        # /v1/audio/speech -> audio_speech

        parts = path.strip("/").split("/")

        # Skip api version prefix
        if parts and parts[0].startswith("v"):
            parts = parts[1:]

        if not parts:
            return "unknown"

        # Join remaining parts
        return "_".join(parts)

    def _categorize_status(self, status_code: int) -> str:
        """Categorize HTTP status code."""
        if 200 <= status_code < 300:
            return "success"
        elif status_code == 429:
            return "rate_limited"
        elif 400 <= status_code < 500:
            return "client_error"
        else:
            return "server_error"


class ModelTrackingMiddleware(BaseHTTPMiddleware):
    """Middleware to extract and track model from request body.

    This middleware parses JSON bodies to extract the model field
    and stores it in request.state for use by MetricsMiddleware.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Extract model from request body."""
        # Only process POST requests to API endpoints
        if request.method == "POST" and request.url.path.startswith("/v1/"):
            try:
                # Try to get cached body or read it
                body = await request.body()
                if body:
                    import json

                    data = json.loads(body)
                    model = data.get("model", "unknown")
                    request.state.model = model
            except Exception:
                request.state.model = "unknown"
        else:
            request.state.model = "unknown"

        return await call_next(request)
