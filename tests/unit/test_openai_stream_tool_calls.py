"""OpenAI (Responses API) streaming must assemble tool calls correctly.

Regression for: the adapter read `.call_id`/`.name` off the
`response.function_call_arguments.done` event, which doesn't carry them — they live on the earlier
`response.output_item.added` event. The bug only fired once streamed tool_calls were actually
forwarded to clients (it was dead code before), and broke every OpenAI reasoning-model agent turn
with `'ResponseFunctionCallArgumentsDoneEvent' object has no attribute 'call_id'`.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from mlpal_assistants_service.adapters.base import ToolDefinition
from mlpal_assistants_service.adapters.openai import OpenAIAdapter


def _events():
    """Fake Responses-API streaming events for a single function call."""
    return [
        SimpleNamespace(type="response.output_text.delta", delta="Let me check. "),
        SimpleNamespace(
            type="response.output_item.added",
            item=SimpleNamespace(type="function_call", id="item_1", call_id="call_abc", name="bash"),
        ),
        SimpleNamespace(
            type="response.function_call_arguments.done",
            item_id="item_1",
            arguments='{"cmd": "ls"}',
        ),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                output=[SimpleNamespace(type="function_call")],
                status="completed",
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            ),
        ),
    ]


@pytest.mark.asyncio
async def test_openai_stream_assembles_tool_call_from_added_and_done() -> None:
    adapter = OpenAIAdapter(api_key="test")

    async def fake_stream(**_kwargs):
        async def gen():
            for e in _events():
                yield e
        return gen()

    tools = [ToolDefinition(name="bash", description="run a shell command", parameters={"type": "object"})]

    with patch.object(adapter._client.responses, "create", new=AsyncMock(side_effect=fake_stream)):
        chunks = [c async for c in adapter.chat_stream(model="gpt-5.5", messages=[{"role": "user", "content": "hi"}], tools=tools)]

    tool_chunks = [c for c in chunks if c.tool_calls]
    assert len(tool_chunks) == 1
    tc = tool_chunks[0].tool_calls[0]
    assert tc["id"] == "call_abc"               # from output_item.added, not the done event
    assert tc["function"]["name"] == "bash"
    assert tc["function"]["arguments"] == '{"cmd": "ls"}'

    final = [c for c in chunks if c.done]
    assert final and final[0].finish_reason == "tool_calls"
    assert any(c.content for c in chunks)  # text delta preserved
