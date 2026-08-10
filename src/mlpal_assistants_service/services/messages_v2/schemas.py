"""Light request validation for /v2/messages.

Deliberately minimal: parse JSON, require `model` + `messages`, capture the
`stream` flag and metadata. We do NOT impose a strict Anthropic schema — the
whole point of v2 is faithful passthrough, so unknown/new Anthropic fields must
survive to the provider. Heavy validation belongs to the provider, which
returns a faithful Anthropic error envelope we surface unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


class InvalidMessagesRequest(ValueError):
    """Raised for a request we can reject up front (bad JSON, missing fields)."""


@dataclass
class ValidatedRequest:
    raw_body: bytes
    body: dict[str, Any]
    model: str
    stream: bool
    metadata: dict[str, Any] = field(default_factory=dict)


def validate(raw_body: bytes) -> ValidatedRequest:
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as e:
        raise InvalidMessagesRequest("Request body is not valid JSON") from e
    if not isinstance(body, dict):
        raise InvalidMessagesRequest("Request body must be a JSON object")

    model = body.get("model")
    if not isinstance(model, str) or not model:
        raise InvalidMessagesRequest("`model` is required")
    if "messages" not in body:
        raise InvalidMessagesRequest("`messages` is required")

    md = body.get("metadata")
    return ValidatedRequest(
        raw_body=raw_body,
        body=body,
        model=model,
        stream=bool(body.get("stream")),
        metadata=md if isinstance(md, dict) else {},
    )
