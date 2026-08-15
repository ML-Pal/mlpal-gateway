"""Anthropic backend selection + request building for the v2 native path.

Backend follows `MLPAL_ANTHROPIC_BACKENDS` (the same priority list the
adapter layer uses) — the first CONFIGURED entry serves the native
/v1/messages wire. `first_party` is api.anthropic.com with x-api-key auth;
`bedrock` is the bedrock-mantle Anthropic-format endpoint with SigV4 auth
and the mantle body/beta quirk-filters (reused from services/bedrock_mantle,
which has served the managed CDE passthrough since 2026-05).

Interface: `url` + `prepare(body_bytes, client_headers) -> (content, headers)`.
prepare owns any body adaptation because SigV4 signs the exact bytes.
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

    def serves(self, provider_model_id: str) -> bool:
        return True

    def prepare(
        self, body: bytes, client_headers: Mapping[str, str]
    ) -> tuple[bytes, dict[str, str]]:
        h = {
            "x-api-key": self._api_key,
            "anthropic-version": client_headers.get("anthropic-version")
            or self._default_version,
            "content-type": "application/json",
        }
        # Forward anthropic-beta unfiltered (locked decision for v2-A).
        beta = client_headers.get("anthropic-beta")
        if beta:
            h["anthropic-beta"] = beta
        return body, h


class AnthropicBedrockBackend:
    """Claude native wire via bedrock-mantle: adapt body (anthropic_version,
    model prefix, quirk-filters), filter betas mantle rejects, SigV4-sign."""

    name = "bedrock"

    def __init__(self, settings: Settings) -> None:
        import json as _json

        from mlpal_assistants_service.services.bedrock_mantle import BedrockMantleClient

        self._signer = BedrockMantleClient(region=settings.bedrock_mantle_region)
        self.url = self._signer.url
        # Mantle serves a SUBSET of bedrock-runtime (see config). Empty/unset
        # list → serve nothing natively; core falls back to the adapter path,
        # which is gated on the live-verified bedrock_anthropic_models map.
        self._models: frozenset[str] = frozenset(
            _json.loads(settings.bedrock_mantle_models or "[]")
        )

    def serves(self, provider_model_id: str) -> bool:
        return provider_model_id in self._models

    def prepare(
        self, body: bytes, client_headers: Mapping[str, str]
    ) -> tuple[bytes, dict[str, str]]:
        from mlpal_assistants_service.services.bedrock_mantle import (
            filter_anthropic_beta_header,
        )

        adapted, _, _removed = self._signer.adapt_body(body)
        beta, _dropped = filter_anthropic_beta_header(client_headers.get("anthropic-beta"))
        extra = {"anthropic-beta": beta} if beta else None
        return adapted, self._signer.sign(adapted, extra)


# Backend cache keyed by the config that shapes it — construction is per
# process, not per request (the bedrock backend builds a boto3 Session).
_backends: dict[tuple, object] = {}


def get_anthropic_backend(
    settings: Settings,
) -> AnthropicFirstPartyBackend | AnthropicBedrockBackend:
    """Resolve the native-path backend: first configured entry of
    MLPAL_ANTHROPIC_BACKENDS. `vertex` is adapter-path only for now (its
    native wire needs OAuth token refresh — tracked in the worklog)."""
    key = (
        settings.anthropic_backends,
        settings.anthropic_api_key,
        settings.anthropic_base_url,
        settings.bedrock_mantle_region,
        settings.bedrock_mantle_models,
    )
    hit = _backends.get(key)
    if hit is not None:
        return hit  # type: ignore[return-value]
    for name in (n.strip() for n in settings.anthropic_backends.split(",")):
        backend: AnthropicFirstPartyBackend | AnthropicBedrockBackend | None = None
        if name == "first_party" and settings.anthropic_api_key:
            backend = AnthropicFirstPartyBackend(settings)
        elif name == "bedrock":
            backend = AnthropicBedrockBackend(settings)
        if backend is not None:
            _backends[key] = backend
            return backend
    raise ValueError(
        f"No usable native Anthropic backend in "
        f"MLPAL_ANTHROPIC_BACKENDS={settings.anthropic_backends!r} "
        "(first_party needs ANTHROPIC_API_KEY; bedrock needs AWS creds)"
    )
