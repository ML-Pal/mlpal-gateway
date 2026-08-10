"""Streaming must carry tool calls.

Regression test for the gap where the SSE/streaming path silently dropped tool_calls and
finish_reason — the adapter produced them, but the service layer re-wrapped chunks into the public
schema without those fields, so an agent loop driven off the stream could never see a tool call.
This forced agent loops onto the non-streaming path, which buffers the whole response and trips the
load balancer's idle timeout on long turns.

We assert the service re-emits tool_calls (mid-stream) and finish_reason (final chunk), matching the
non-streaming response shape.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock


import pytest

from mlpal_assistants_service.adapters.base import StreamChunk as AdapterStreamChunk
from mlpal_assistants_service.adapters.base import TokenUsage
from mlpal_assistants_service.schemas.chat import ChatCompletionRequest
from mlpal_assistants_service.services.chat import ChatService


def _adapter_stream() -> AsyncIterator[AdapterStreamChunk]:
    """Mimic the Anthropic adapter: a text delta, then a completed tool call, then a final chunk."""

    async def gen() -> AsyncIterator[AdapterStreamChunk]:
        yield AdapterStreamChunk(content="Let me look that up.", done=False)
        yield AdapterStreamChunk(
            content="",
            done=False,
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "bash", "arguments": '{"cmd": "ls"}'},
                }
            ],
        )
        yield AdapterStreamChunk(
            content="",
            done=True,
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            finish_reason="tool_calls",
        )

    return gen()


def _build_service_with_mocks() -> ChatService:
    service = ChatService(session=MagicMock(), redis_client=None)

    caps = MagicMock(supports_tools=True, supports_structured_output=True, supports_mcp=True)
    adapter = MagicMock()
    adapter.get_model_capabilities.return_value = caps
    adapter.chat_stream.return_value = _adapter_stream()

    @asynccontextmanager
    async def _breaker():
        yield

    model_info = MagicMock(provider="anthropic")
    service._router.get_adapter_with_breaker_for_operation = AsyncMock(
        return_value=(adapter, "claude-sonnet-4-6", _breaker(), model_info, None)
    )
    service._billing.can_make_request_cached = AsyncMock(return_value=(True, None, True))
    service._pricing.calculate_compute_units = AsyncMock(
        return_value=Decimal("0.001")
    )
    # Keep the test hermetic — close the background coroutine instead of scheduling it.
    service._fire_and_forget = lambda coro: coro.close()
    return service


@pytest.mark.asyncio
async def test_chat_stream_forwards_tool_calls_and_finish_reason() -> None:
    service = _build_service_with_mocks()
    request = ChatCompletionRequest(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": "list the files"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "bash",
                    "description": "run a shell command",
                    "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
                },
            }
        ],
        stream=True,
    )

    chunks = [c async for c in service.chat_stream(user_id=1, api_key_id=1, request=request)]

    # The tool call survives to the public stream, with the non-streaming shape.
    tool_chunks = [c for c in chunks if c.tool_calls]
    assert len(tool_chunks) == 1
    tc = tool_chunks[0].tool_calls[0]
    assert tc.id == "call_1"
    assert tc.function.name == "bash"
    assert tc.function.arguments == '{"cmd": "ls"}'

    # The final chunk carries finish_reason and cost.
    final = [c for c in chunks if c.done]
    assert len(final) == 1
    assert final[0].finish_reason == "tool_calls"
    assert final[0].cost is not None

    # Text delta still flows.
    assert any(c.content for c in chunks)


def test_stream_chunk_preserves_boundary_whitespace() -> None:
    """A streamed delta must keep leading/trailing spaces — otherwise reassembled text loses the
    spaces at every chunk boundary ("Let" + " me" -> "Letme"). BaseSchema strips whitespace; the
    StreamChunk override must opt out."""
    from mlpal_assistants_service.schemas.chat import StreamChunk

    assert StreamChunk(content=" me").content == " me"
    assert StreamChunk(content="Let ").content == "Let "
    # Reassembly fidelity across a boundary.
    assert StreamChunk(content="Let").content + StreamChunk(content=" me").content == "Let me"
