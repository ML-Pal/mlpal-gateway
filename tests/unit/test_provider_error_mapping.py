"""Tests for provider-error → HTTP status mapping.

Regression guard for the 2026-06-03 false alarm: a provider 400 (e.g. OpenAI
rejecting max_output_tokens=10) was surfaced as HTTP 502, making a bad client
request look like a gateway outage.
"""

import pytest

from mlpal_assistants_service.adapters.base import provider_status_code
from mlpal_assistants_service.core.exceptions import (
    ProviderError,
    ProviderUnavailableError,
    http_status_for_provider_error,
)


def _err(status_code):
    return ProviderError(message="boom", provider="openai", status_code=status_code)


class TestHttpStatusMapping:
    @pytest.mark.parametrize("code", [400, 422])
    def test_client_bad_request_surfaces_same_4xx(self, code):
        # The client's request was invalid (e.g. max_output_tokens too small).
        assert http_status_for_provider_error(_err(code)) == code

    def test_rate_limit_maps_to_429(self):
        assert http_status_for_provider_error(_err(429)) == 429

    @pytest.mark.parametrize("code", [401, 403, 404, 500, 503, None])
    def test_gateway_or_upstream_failures_map_to_502(self, code):
        # Our-side auth/config (401/403/404), provider 5xx, and unknown/connection
        # errors are NOT the client's fault → 502, never a misleading 4xx.
        assert http_status_for_provider_error(_err(code)) == 502

    def test_explicit_unavailable_maps_to_503(self):
        exc = ProviderUnavailableError(message="down", provider="openai", status_code=500)
        assert http_status_for_provider_error(exc) == 503


class TestProviderStatusCodeExtraction:
    def test_status_code_attr(self):
        e = Exception()
        e.status_code = 400  # OpenAI/Anthropic SDK shape
        assert provider_status_code(e) == 400

    def test_response_status_code(self):
        class _Resp:
            status_code = 429

        e = Exception()
        e.response = _Resp()  # httpx-based shape
        assert provider_status_code(e) == 429

    def test_code_attr(self):
        e = Exception()
        e.code = 503  # google-genai shape
        assert provider_status_code(e) == 503

    def test_none_when_absent(self):
        assert provider_status_code(Exception("connection reset")) is None

    def test_non_int_status_ignored(self):
        e = Exception()
        e.status_code = "weird"
        assert provider_status_code(e) is None
