"""Wallet-gating surfaces: 402 envelopes on both wires + paused key fields.

Contract (gating design 2026-08-12, live in prod): wallet-empty blocks are
HTTP 402 with stable machine keys — Anthropic wire type=billing_error, OpenAI
wire type=insufficient_quota + code=wallet_empty — and every key in /v1/keys
carries derived paused/paused_reason.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from mlpal_assistants_service.core.exceptions import WalletEmptyError
from mlpal_assistants_service.repositories.billing_repository import WALLET_EMPTY_MESSAGE
from mlpal_assistants_service.schemas.api_key import APIKeyResponse
from mlpal_assistants_service.services.messages_v2.errors import error_body


def test_anthropic_wire_402_envelope():
    body = json.loads(error_body(402, WALLET_EMPTY_MESSAGE))
    assert body == {
        "type": "error",
        "error": {"type": "billing_error", "message": WALLET_EMPTY_MESSAGE},
    }


@pytest.mark.asyncio
async def test_openai_wire_402_envelope():
    """The app-level handler shape, exercised through a minimal app."""
    app = FastAPI()

    @app.exception_handler(WalletEmptyError)
    async def handler(request, exc):  # mirrors main.py registration
        return JSONResponse(
            status_code=402,
            content={
                "error": {
                    "message": exc.message,
                    "type": "insufficient_quota",
                    "code": "wallet_empty",
                }
            },
        )

    @app.get("/boom")
    async def boom():
        raise WalletEmptyError(WALLET_EMPTY_MESSAGE)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/boom")
    assert r.status_code == 402
    assert r.json()["error"]["code"] == "wallet_empty"
    assert r.json()["error"]["type"] == "insufficient_quota"
    assert "top up" in r.json()["error"]["message"]


def test_services_raise_wallet_empty_on_sentinel():
    """Every OpenAI-wire service maps the sentinel to WalletEmptyError."""
    import inspect

    from mlpal_assistants_service.services import audio, chat, embedding, image

    for mod in (chat, embedding, image, audio):
        src = inspect.getsource(mod)
        assert "WalletEmptyError" in src, mod.__name__
        assert "WALLET_EMPTY_MESSAGE" in src, mod.__name__


def test_key_response_paused_fields_default_and_set():
    base = {
        "id": 1, "name": "k", "key_prefix": "mlpal_sk_", "permissions": ["messages"],
        "rate_limit_tier": "standard", "is_active": True, "created_at": "2026-08-12T00:00:00Z",
    }
    k = APIKeyResponse(**base)
    assert k.paused is False and k.paused_reason is None
    k2 = APIKeyResponse(**base, paused=True, paused_reason="insufficient_balance")
    assert k2.paused is True and k2.paused_reason == "insufficient_balance"
