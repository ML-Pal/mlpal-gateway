"""Shared emitter: adapter output → Anthropic Messages wire shape.

This is the reuse artifact for every non-Anthropic edge (OpenAI in v2-B, Google
in v2-C). It turns the provider-neutral adapter results — ``AdapterResponse``
for non-streaming, a ``StreamChunk`` async stream for streaming — into bytes
that are wire-identical to what a client expects from Anthropic's Messages API:

  - non-streaming: one Anthropic `message` JSON object
  - streaming: the SSE event sequence
      message_start
      → (content_block_start / content_block_delta* / content_block_stop)+
      → message_delta → message_stop

The Anthropic edge bypasses this entirely (native passthrough). Built once here
so OpenAI and Google share exactly one translation of the output surface.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Callable

from mlpal_assistants_service.adapters.base import AdapterResponse, StreamChunk, TokenUsage

# OpenAI/Google finish reasons → Anthropic stop_reason.
_STOP_REASON = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "end_turn",
    None: "end_turn",
}


def stop_reason(finish_reason: str | None) -> str:
    return _STOP_REASON.get(finish_reason, "end_turn")


def usage_block(usage: TokenUsage | None) -> dict[str, int]:
    """Anthropic-faithful usage block. Anthropic's ``input_tokens`` excludes the
    cache-read prefix (it's reported separately), so we subtract the cached
    portion that OpenAI/Google fold into their input total."""
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0,
                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    cached = int(usage.cached_tokens or 0)
    return {
        "input_tokens": max(int(usage.input_tokens or 0) - cached, 0),
        "output_tokens": int(usage.output_tokens or 0),
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": 0,
    }


# Gemini thinking models attach a `thought_signature` to each function call that
# MUST be echoed back verbatim on the next turn or the API 400s. The Anthropic
# wire has no field for it, so we ride it on the tool_use `id` — the one field
# every client echoes back (in the tool_use block AND tool_result.tool_use_id).
# translate_in splits it back off. Stateless; no server-side stash. The signature
# is small (~a few hundred bytes) so the id stays well within limits.
TOOL_SIG_DELIM = "::gts::"


def _tool_use_block(tc: dict[str, Any]) -> dict[str, Any]:
    fn = tc.get("function") or {}
    raw_args = fn.get("arguments")
    try:
        parsed = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
    except json.JSONDecodeError:
        parsed = {}
    tool_id = tc.get("id")
    sig = tc.get("thought_signature")
    if sig:
        tool_id = f"{tool_id}{TOOL_SIG_DELIM}{sig}"
    return {"type": "tool_use", "id": tool_id, "name": fn.get("name"), "input": parsed}


def content_blocks(content: str, tool_calls: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if content:
        blocks.append({"type": "text", "text": content})
    for tc in tool_calls or []:
        blocks.append(_tool_use_block(tc))
    return blocks


def message_json(resp: AdapterResponse, message_id: str, model_tag: str) -> bytes:
    """Non-streaming: AdapterResponse → one Anthropic `message` JSON object."""
    blocks = content_blocks(resp.content, resp.tool_calls)
    # Derive stop_reason from the output itself: a turn that produced tool_use
    # blocks is always `tool_use`, regardless of the provider's own finish_reason
    # (Google reports "stop" even when it calls a tool).
    has_tool = any(b["type"] == "tool_use" for b in blocks)
    body = {
        "id": message_id,
        "type": "message",
        "role": "assistant",
        "model": model_tag,
        "content": blocks,
        "stop_reason": "tool_use" if has_tool else stop_reason(resp.finish_reason),
        "stop_sequence": None,
        "usage": usage_block(resp.usage),
    }
    return json.dumps(body).encode()


def _sse(event_type: str, data: dict[str, Any]) -> bytes:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n".encode()


async def stream_anthropic_sse(
    chunks: AsyncIterator[StreamChunk],
    message_id: str,
    model_tag: str,
    on_final: Callable[[TokenUsage | None, str, bool], None],
) -> AsyncIterator[bytes]:
    """Translate a StreamChunk stream into Anthropic SSE bytes.

    Text deltas open content block 0 lazily; each completed tool call becomes a
    subsequent tool_use block whose arguments are emitted as a single
    input_json_delta (the OpenAI Responses adapter delivers tool arguments whole,
    not incrementally). ``on_final`` is invoked with the terminal usage and
    stop_reason before message_stop so the edge can report billing.

    message_start.usage.input_tokens is 0 here on purpose: OpenAI/Gemini only
    report prompt tokens at stream END, and we never fabricate an estimate. The
    authoritative provider count is delivered factually in the terminal
    message_delta (and in usage_logs/billing).
    """
    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": message_id, "type": "message", "role": "assistant", "model": model_tag,
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": usage_block(None),
        },
    })

    thinking_open = False
    thinking_index = -1
    text_open = False
    tool_emitted = False
    visible_emitted = False  # any text or tool output — drives empty-completion detection
    next_index = 0
    text_index = -1
    final_usage: TokenUsage | None = None
    final_finish: str | None = None

    async for chunk in chunks:
        # Reasoning/thinking arrives before the answer. Render it as an Anthropic
        # `thinking` content block (block 0) so clients can show live reasoning;
        # it's kept out of the text content. (No signature_delta — we're
        # translating, not producing Anthropic-signed thinking.)
        thinking = getattr(chunk, "thinking", None)
        if thinking and not text_open and not tool_emitted:
            if not thinking_open:
                thinking_index = next_index
                next_index += 1
                thinking_open = True
                yield _sse("content_block_start", {
                    "type": "content_block_start", "index": thinking_index,
                    "content_block": {"type": "thinking", "thinking": ""},
                })
            yield _sse("content_block_delta", {
                "type": "content_block_delta", "index": thinking_index,
                "delta": {"type": "thinking_delta", "thinking": thinking},
            })

        if chunk.content:
            visible_emitted = True
            if thinking_open:
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": thinking_index})
                thinking_open = False
            if not text_open:
                text_index = next_index
                next_index += 1
                text_open = True
                yield _sse("content_block_start", {
                    "type": "content_block_start", "index": text_index,
                    "content_block": {"type": "text", "text": ""},
                })
            yield _sse("content_block_delta", {
                "type": "content_block_delta", "index": text_index,
                "delta": {"type": "text_delta", "text": chunk.content},
            })

        for tc in chunk.tool_calls or []:
            if thinking_open:
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": thinking_index})
                thinking_open = False
            if text_open:
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_index})
                text_open = False
            tool_emitted = True
            visible_emitted = True
            block = _tool_use_block(tc)
            index = next_index
            next_index += 1
            yield _sse("content_block_start", {
                "type": "content_block_start", "index": index,
                "content_block": {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}},
            })
            yield _sse("content_block_delta", {
                "type": "content_block_delta", "index": index,
                "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"])},
            })
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": index})

        if chunk.usage is not None:
            final_usage = chunk.usage
        if chunk.finish_reason is not None:
            final_finish = chunk.finish_reason

    if thinking_open:
        yield _sse("content_block_stop", {"type": "content_block_stop", "index": thinking_index})
    if text_open:
        yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_index})

    reason = "tool_use" if tool_emitted else stop_reason(final_finish)
    # A reasoning model can burn the whole token budget on hidden reasoning and
    # emit nothing visible: stop_reason=max_tokens with no text/tool output.
    empty_completion = not visible_emitted and reason == "max_tokens"
    on_final(final_usage, reason, empty_completion)
    yield _sse("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": reason, "stop_sequence": None},
        "usage": usage_block(final_usage),
    })
    yield _sse("message_stop", {"type": "message_stop"})
