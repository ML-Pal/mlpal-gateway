"""Anthropic provider edge — native Anthropic-Messages passthrough.

The faithful path: forward the (model-rewritten) Anthropic body to the
configured Anthropic backend and pipe the response straight through —
**raw SSE bytes, never parsed-and-reserialized** — so the wire shape is
byte-identical to talking to Anthropic directly. A copy of the stream is teed
into the Anthropic SSE parser only to extract usage for billing (exactly the
v1/messages technique). The core owns heartbeat + telemetry; this edge only
produces bytes and reports usage via ctx.
"""

from __future__ import annotations

import asyncio
import json
import weakref
from collections.abc import AsyncIterator
from typing import Any

import httpx

from mlpal_assistants_service.services.bedrock_mantle import (
    parse_non_streaming_usage,
    parse_sse_event,
)
from mlpal_assistants_service.services.messages_v2.anthropic_backend import (
    AnthropicFirstPartyBackend,
)
from mlpal_assistants_service.services.messages_v2.edges import EdgeResult, RequestContext
from mlpal_assistants_service.services.messages_v2.schemas import ValidatedRequest
from mlpal_assistants_service.services.messages_v2.usage import CanonicalUsage

# Connection pool with the lifetime of the running event loop. A client per
# request would pay a fresh TCP+TLS handshake to the provider on EVERY request —
# connection reuse is the single largest per-request saving on this path.
# Weak-keyed by loop (never reuse a client across loops; ids recycle, objects
# don't) and invalidated when the AsyncClient constructor changes (tests
# monkeypatch it per-test). In production: one loop, one constructor, one
# cached client for the process lifetime.
_clients: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _shared_client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    ctor = httpx.AsyncClient
    cached = _clients.get(loop)
    if cached is not None:
        client, cached_ctor = cached
        if cached_ctor is ctor and not client.is_closed:
            return client
    client = ctor(
        timeout=None,
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
    )
    _clients[loop] = (client, ctor)
    return client


class AnthropicEdge:
    def __init__(self, backend: AnthropicFirstPartyBackend, timeout: float = 120.0) -> None:
        self._backend = backend
        self._timeout = timeout

    def _outbound(self, req: ValidatedRequest, ctx: RequestContext) -> tuple[bytes, dict[str, str]]:
        # Rewrite `model` to the provider's id (first-party == the tag, but the
        # router is the source of truth) and re-serialize. The RESPONSE is what
        # must stay byte-faithful, not the request.
        body = dict(req.body)
        body["model"] = ctx.provider_model_id
        return json.dumps(body).encode(), self._backend.headers(ctx.headers)

    async def invoke(self, req: ValidatedRequest, ctx: RequestContext) -> EdgeResult:
        content, headers = self._outbound(req, ctx)
        resp = await _shared_client().post(
            self._backend.url, content=content, headers=headers, timeout=self._timeout
        )
        usage_dict, msg_id = parse_non_streaming_usage(resp.content)
        ctx.report(
            CanonicalUsage.from_anthropic(usage_dict) if resp.status_code == 200 else None,
            resp.status_code,
            msg_id,
        )
        return EdgeResult(
            status_code=resp.status_code,
            body=resp.content,
            media_type=resp.headers.get("content-type", "application/json"),
        )

    async def stream(self, req: ValidatedRequest, ctx: RequestContext) -> AsyncIterator[bytes]:
        content, headers = self._outbound(req, ctx)
        usage_dict: dict[str, Any] = {}
        msg_id: str | None = None
        status_code = 0
        buf = b""
        async with _shared_client().stream(
            "POST", self._backend.url, content=content,
            headers={**headers, "accept": "text/event-stream"},
            timeout=self._timeout,
        ) as resp:
            status_code = resp.status_code
            # aiter_bytes (not aiter_raw): decode the transport Content-
            # Encoding (Anthropic gzips the SSE stream) so the client gets
            # plain SSE. Still event-faithful — we never parse/reserialize
            # the events, only decompress the transport layer. (aiter_raw
            # would forward compressed bytes with no Content-Encoding header
            # -> the client sees garbage.)
            async for chunk in resp.aiter_bytes():
                yield chunk  # event-faithful passthrough
                buf += chunk
                while b"\n\n" in buf:
                    raw_event, buf = buf.split(b"\n\n", 1)
                    event_type, data = parse_sse_event(raw_event)
                    if not data:
                        continue
                    if event_type == "message_start":
                        msg = data.get("message", {}) or {}
                        msg_id = msg.get("id") or msg_id
                        usage_dict.update(msg.get("usage") or {})
                    elif event_type == "message_delta":
                        usage_dict.update(data.get("usage") or {})
        ctx.report(
            CanonicalUsage.from_anthropic(usage_dict) if status_code == 200 else None,
            status_code,
            msg_id,
        )
