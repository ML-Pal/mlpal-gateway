"""Tests for the SSE streaming heartbeat and OpenAI reasoning-event forwarding.

Regression guard: OpenAI reasoning models (gpt-5.5, o-series) go byte-silent
during their reasoning phase, which on heavy requests outlasts client/ALB idle
timeouts and stalls the stream. Two fixes:
  1. The streaming route emits an SSE heartbeat (": ping") during silence.
  2. The OpenAI adapter forwards reasoning events as empty keepalive chunks.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import mlpal_assistants_service.api.v1.chat as chat_route
from mlpal_assistants_service.api.v1.chat import create_chat_completion_stream


def _chunk(content="", done=False, finish_reason=None):
    return SimpleNamespace(
        content=content, done=done, tool_calls=None, finish_reason=finish_reason, cost=None
    )


async def _collect(response) -> str:
    out = []
    async for part in response.body_iterator:
        out.append(part.decode() if isinstance(part, (bytes, bytearray)) else part)
    return "".join(out)


@pytest.mark.asyncio
async def test_heartbeat_emitted_during_silence(monkeypatch):
    # Shrink the heartbeat interval so a short silence triggers it.
    monkeypatch.setattr(chat_route, "_STREAM_HEARTBEAT_INTERVAL", 0.05)

    async def slow_stream(**kwargs):
        await asyncio.sleep(0.18)  # byte-silent longer than the heartbeat interval
        yield _chunk(content="Hello", done=False)
        yield _chunk(content="", done=True, finish_reason="stop")

    api_key = MagicMock(user_id=1, id=2, rate_limit_tier="standard")
    api_key.has_permission.return_value = True
    chat_service = MagicMock()
    chat_service.chat_stream = slow_stream

    resp = await create_chat_completion_stream(
        MagicMock(), MagicMock(), api_key, chat_service
    )
    body = await _collect(resp)

    assert ": ping" in body  # heartbeat fired during the silent phase
    assert '"content": "Hello"' in body
    assert "data: [DONE]" in body
    # Heartbeat must come before the first real data chunk.
    assert body.index(": ping") < body.index('"content": "Hello"')


@pytest.mark.asyncio
async def test_no_heartbeat_when_chunks_flow(monkeypatch):
    monkeypatch.setattr(chat_route, "_STREAM_HEARTBEAT_INTERVAL", 0.5)

    async def fast_stream(**kwargs):
        yield _chunk(content="hi", done=False)
        yield _chunk(content="", done=True, finish_reason="stop")

    api_key = MagicMock(user_id=1, id=2, rate_limit_tier="standard")
    api_key.has_permission.return_value = True
    chat_service = MagicMock()
    chat_service.chat_stream = fast_stream

    resp = await create_chat_completion_stream(
        MagicMock(), MagicMock(), api_key, chat_service
    )
    body = await _collect(resp)

    assert ": ping" not in body  # no silence -> no heartbeat
    assert "data: [DONE]" in body


@pytest.mark.asyncio
async def test_producer_cancelled_on_client_disconnect(monkeypatch):
    # Bounded queue + a producer that runs ahead: on client disconnect (closing
    # the response generator), the producer must be cancelled and not hang even
    # if it's blocked on a full-queue `put`.
    monkeypatch.setattr(chat_route, "_STREAM_QUEUE_MAXSIZE", 4)
    monkeypatch.setattr(chat_route, "_STREAM_HEARTBEAT_INTERVAL", 5.0)
    state = {"cancelled": False}

    async def infinite_stream(**kwargs):
        try:
            i = 0
            while True:
                yield _chunk(content=f"t{i}", done=False)
                i += 1
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    api_key = MagicMock(user_id=1, id=2, rate_limit_tier="standard")
    api_key.has_permission.return_value = True
    chat_service = MagicMock()
    chat_service.chat_stream = infinite_stream

    resp = await create_chat_completion_stream(
        MagicMock(), MagicMock(), api_key, chat_service
    )
    it = resp.body_iterator
    await it.__anext__()  # read one chunk; producer races ahead and fills the bounded queue
    await asyncio.wait_for(it.aclose(), timeout=2.0)  # disconnect — must return promptly

    assert state["cancelled"] is True


@pytest.mark.asyncio
async def test_openai_adapter_forwards_reasoning_events():
    from mlpal_assistants_service.adapters.openai import OpenAIAdapter

    events = [
        SimpleNamespace(type="response.reasoning_summary_text.delta", delta="thinking..."),
        SimpleNamespace(type="response.output_text.delta", delta="Answer"),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                output=[], status="completed",
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            ),
        ),
    ]

    class _FakeStream:
        def __aiter__(self):
            async def gen():
                for e in events:
                    yield e
            return gen()

    adapter = OpenAIAdapter(api_key="test")
    adapter._client = MagicMock()
    adapter._client.responses.create = AsyncMock(return_value=_FakeStream())

    chunks = [
        c async for c in adapter.chat_stream(
            model="gpt-5.5", messages=[{"role": "user", "content": "hi"}], max_tokens=64
        )
    ]

    # The reasoning event produced a keepalive chunk (empty content, not done)...
    assert any(c.content == "" and not c.done for c in chunks)
    # ...and reasoning text was NOT surfaced as content.
    assert not any("thinking" in (c.content or "") for c in chunks)
    # The real text delta still came through.
    assert any(c.content == "Answer" for c in chunks)
