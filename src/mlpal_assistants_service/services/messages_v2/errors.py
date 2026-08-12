"""Anthropic-style error envelope for /v2/messages.

The harness's retry/backoff classifier keys off the Anthropic error shape
(`{type:"error", error:{type, message}}`), the HTTP status, and `retry-after`
on 429/529. The core emits errors through here so every edge fails identically.
"""

from __future__ import annotations

import json

# Anthropic error `type` strings by HTTP status (from Anthropic's API docs).
_ERROR_TYPE_BY_STATUS = {
    400: "invalid_request_error",
    401: "authentication_error",
    402: "billing_error",
    403: "permission_error",
    404: "not_found_error",
    413: "request_too_large",
    429: "rate_limit_error",
    500: "api_error",
    529: "overloaded_error",
}


def error_type_for_status(status_code: int) -> str:
    if status_code in _ERROR_TYPE_BY_STATUS:
        return _ERROR_TYPE_BY_STATUS[status_code]
    return "invalid_request_error" if 400 <= status_code < 500 else "api_error"


def error_body(status_code: int, message: str) -> bytes:
    """Anthropic error envelope as JSON bytes."""
    return json.dumps(
        {"type": "error", "error": {"type": error_type_for_status(status_code), "message": message}}
    ).encode()
