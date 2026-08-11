"""Anthropic backend selection + first-party request building for v2.

Backend is a config choice (`settings.anthropic_messages_backend`), never
hardcoded — so Anthropic models can move back onto Bedrock later by adding a
backend here, without touching the edge. v2-A ships `first_party` only.

First-party differs from the v1 bedrock-mantle path: `api.anthropic.com`,
`x-api-key` auth (no SigV4), no `anthropic.` model prefix, and `anthropic-beta`
forwarded UNFILTERED (first-party accepts the standard caching/thinking betas;
the mantle quirk-filter does not apply).
"""

from __future__ import annotations

from collections.abc import Mapping

from mlpal_assistants_service.core.config import Settings


class AnthropicFirstPartyBackend:
    """Builds the URL + headers for a first-party Anthropic Messages call."""

    name = "first_party"

    def __init__(self, settings: Settings) -> None:
        self.url = settings.anthropic_base_url.rstrip("/") + "/v1/messages"
        self._api_key = settings.anthropic_api_key
        self._default_version = settings.anthropic_api_version

    def headers(self, client_headers: Mapping[str, str]) -> dict[str, str]:
        h = {
            "x-api-key": self._api_key,
            "anthropic-version": client_headers.get("anthropic-version") or self._default_version,
            "content-type": "application/json",
        }
        # Forward anthropic-beta unfiltered (locked decision for v2-A).
        beta = client_headers.get("anthropic-beta")
        if beta:
            h["anthropic-beta"] = beta
        return h


def get_anthropic_backend(settings: Settings) -> AnthropicFirstPartyBackend:
    """Resolve the configured Anthropic backend. Only first_party in v2-A;
    a bedrock backend would slot in here behind the same interface."""
    backend = settings.anthropic_messages_backend
    if backend == "first_party":
        return AnthropicFirstPartyBackend(settings)
    raise ValueError(
        f"Unsupported anthropic_messages_backend={backend!r} "
        "(v2-A supports 'first_party' only)"
    )
