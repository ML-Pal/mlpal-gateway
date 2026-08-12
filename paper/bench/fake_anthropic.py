"""Fake Anthropic upstream: canned SSE, zero think time.

Serves POST /v1/messages with a valid Anthropic Messages streaming response
(and a JSON body for non-streaming), so gateway overhead can be measured with
provider variance eliminated.
"""

import json

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

MSG_ID = "msg_fake000000000000000000"
MODEL = "claude-haiku-4-5-20251001"


def sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


CHUNKS = [
    sse("message_start", {"type": "message_start", "message": {
        "id": MSG_ID, "type": "message", "role": "assistant", "model": MODEL,
        "content": [], "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 40, "output_tokens": 1}}}),
    sse("content_block_start", {"type": "content_block_start", "index": 0,
        "content_block": {"type": "text", "text": ""}}),
] + [
    sse("content_block_delta", {"type": "content_block_delta", "index": 0,
        "delta": {"type": "text_delta", "text": f"token{i} "}})
    for i in range(9)
] + [
    sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
    sse("message_delta", {"type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": 9}}),
    sse("message_stop", {"type": "message_stop"}),
]

BODY = {
    "id": MSG_ID, "type": "message", "role": "assistant", "model": MODEL,
    "content": [{"type": "text", "text": "token0 token1 token2"}],
    "stop_reason": "end_turn", "stop_sequence": None,
    "usage": {"input_tokens": 40, "output_tokens": 9},
}


async def messages(request):
    payload = await request.json()
    if payload.get("stream"):
        async def gen():
            for c in CHUNKS:
                yield c
        return StreamingResponse(gen(), media_type="text/event-stream")
    return JSONResponse(BODY)


app = Starlette(routes=[Route("/v1/messages", messages, methods=["POST"])])

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9999, log_level="error")
