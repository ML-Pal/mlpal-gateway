"""Regression test: CORS preflight (OPTIONS) must succeed with CORS headers.

The dashboard at https://mlpal.ai calls https://models.mlpal.ai cross-origin.
If CORSMiddleware isn't the outermost layer, the BaseHTTPMiddleware observability
stack wraps it and can 500 an OPTIONS preflight with no Access-Control-* headers,
which the browser rejects. CORS must be registered last (outermost) so it answers
preflights up front.
"""

import pytest
from httpx import ASGITransport, AsyncClient

# Importing the app exercises the real middleware registration order in main.py.
from mlpal_assistants_service.main import app


@pytest.mark.asyncio
async def test_cors_preflight_returns_cors_headers():
    # ASGITransport does not run lifespan, so no DB/Redis needed — CORS answers
    # the preflight before any route/handler that would touch app state.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://models.mlpal.ai") as client:
        resp = await client.options(
            "/v1/usage/summary",
            headers={
                "Origin": "https://mlpal.ai",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

    assert resp.status_code in (200, 204), f"preflight returned {resp.status_code}"
    assert resp.headers.get("access-control-allow-origin") == "https://mlpal.ai"
    assert resp.headers.get("access-control-allow-credentials") == "true"
    assert "GET" in resp.headers.get("access-control-allow-methods", "")


@pytest.mark.asyncio
async def test_cors_headers_on_actual_request():
    # A normal cross-origin GET also carries an allow-origin header that permits
    # mlpal.ai (either the echoed origin or "*" for a non-credentialed request),
    # even when the request itself is unauthorized -> 401.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://models.mlpal.ai") as client:
        resp = await client.get("/v1/models", headers={"Origin": "https://mlpal.ai"})

    assert resp.headers.get("access-control-allow-origin") in ("https://mlpal.ai", "*")
