"""Cloud serving backends: the same model families served through Azure,
Vertex AI, and Bedrock instead of (or in priority order with) the provider's
first-party API.

Design (worklog 2026-08-14-multicloud-backends):
- These are BACKENDS for existing families, not new catalog providers.
  Catalog rows are unchanged; `MLPAL_<FAMILY>_BACKENDS` picks who serves them.
- Each backend is a thin subclass of its family adapter: constructor swap
  (host/auth) + `serves()` / `backend_model_id()` data. All request/response
  logic is inherited — zero duplication, so family fixes apply everywhere.
- Model maps for Claude-on-cloud are EXPLICIT config (both clouds gate models
  behind per-account enablement; guessing would turn "not enabled" into
  confusing provider errors). `scripts/probe_backends.py` generates the map.
"""

from __future__ import annotations

import json
import logging

import httpx

from mlpal_assistants_service.adapters.anthropic import AnthropicAdapter
from mlpal_assistants_service.adapters.google import GoogleAdapter
from mlpal_assistants_service.adapters.openai import OpenAIAdapter
from mlpal_assistants_service.core.config import get_settings

logger = logging.getLogger(__name__)


def _parse_map(raw: str | None, setting_name: str) -> dict[str, str]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"{setting_name} is not valid JSON: {e}") from e
    if not isinstance(parsed, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()
    ):
        raise ValueError(f"{setting_name} must be a JSON object of string→string")
    return parsed


class AzureOpenAIAdapter(OpenAIAdapter):
    """OpenAI family via Azure's `/openai/v1/` surface.

    The v1 surface is OpenAI-wire-compatible with the standard SDK; the only
    deltas are the base URL, the key, and that `model` means DEPLOYMENT name.
    Convention: name deployments after model IDs and no map is needed;
    MLPAL_AZURE_DEPLOYMENTS overrides per-model and makes `serves()` exact.
    """

    backend_name = "azure"

    def __init__(self) -> None:
        settings = get_settings()
        if not (settings.azure_openai_endpoint and settings.azure_openai_api_key):
            raise RuntimeError(
                "Azure backend requires MLPAL_AZURE_OPENAI_ENDPOINT and "
                "MLPAL_AZURE_OPENAI_API_KEY"
            )
        self._deployments = _parse_map(
            settings.azure_openai_deployments, "MLPAL_AZURE_DEPLOYMENTS"
        )
        super().__init__(
            api_key=settings.azure_openai_api_key,
            base_url=settings.azure_openai_endpoint.rstrip("/") + "/openai/v1/",
        )

    def serves(self, provider_model_id: str) -> bool:
        # No map → identity convention: claim the family and let Azure's
        # DeploymentNotFound surface for undeployed models. With a map,
        # serves() is exact and the console can display truth.
        return provider_model_id in self._deployments if self._deployments else True

    def backend_model_id(self, provider_model_id: str) -> str:
        return self._deployments.get(provider_model_id, provider_model_id)


class VertexGoogleAdapter(GoogleAdapter):
    """Gemini via Vertex AI. Same google-genai SDK, same model IDs — only the
    client constructor differs (ADC auth via GOOGLE_APPLICATION_CREDENTIALS)."""

    backend_name = "vertex"

    def __init__(self) -> None:
        from google import genai

        settings = get_settings()
        if not settings.vertex_project:
            raise RuntimeError("Vertex backend requires MLPAL_VERTEX_PROJECT")
        self._api_key = None
        self._client = genai.Client(
            vertexai=True,
            project=settings.vertex_project,
            location=settings.vertex_location,
        )


class BedrockAnthropicAdapter(AnthropicAdapter):
    """Claude via AWS Bedrock. AsyncAnthropicBedrock is a drop-in for
    AsyncAnthropic (same `.messages` surface, SigV4 auth); model IDs come
    from the explicit MLPAL_BEDROCK_ANTHROPIC_MODELS map."""

    backend_name = "bedrock"

    def __init__(self) -> None:
        from anthropic import AsyncAnthropicBedrock

        settings = get_settings()
        self._model_map = _parse_map(
            settings.bedrock_anthropic_models, "MLPAL_BEDROCK_ANTHROPIC_MODELS"
        )
        if not self._model_map:
            raise RuntimeError(
                "Bedrock Claude backend requires MLPAL_BEDROCK_ANTHROPIC_MODELS "
                "(run scripts/probe_backends.py to generate it)"
            )
        super().__init__(
            api_key="unused-sigv4",
            client=AsyncAnthropicBedrock(
                aws_region=settings.bedrock_mantle_region,
                http_client=httpx.AsyncClient(
                    limits=httpx.Limits(max_connections=300, max_keepalive_connections=60),
                    timeout=httpx.Timeout(120.0, connect=10.0),
                ),
            ),
        )

    def serves(self, provider_model_id: str) -> bool:
        return provider_model_id in self._model_map

    def backend_model_id(self, provider_model_id: str) -> str:
        return self._model_map[provider_model_id]


class VertexAnthropicAdapter(AnthropicAdapter):
    """Claude via Vertex AI (AnthropicVertex, ADC auth). Vertex requires
    per-model Model Garden enablement, so the map is explicit config."""

    backend_name = "vertex"

    def __init__(self) -> None:
        from anthropic import AsyncAnthropicVertex

        settings = get_settings()
        if not settings.vertex_project:
            raise RuntimeError("Vertex backend requires MLPAL_VERTEX_PROJECT")
        self._model_map = _parse_map(
            settings.vertex_anthropic_models, "MLPAL_VERTEX_ANTHROPIC_MODELS"
        )
        if not self._model_map:
            raise RuntimeError(
                "Vertex Claude backend requires MLPAL_VERTEX_ANTHROPIC_MODELS "
                "(models need Model Garden enablement; run scripts/probe_backends.py)"
            )
        super().__init__(
            api_key="unused-adc",
            client=AsyncAnthropicVertex(
                project_id=settings.vertex_project,
                region=settings.vertex_location,
                http_client=httpx.AsyncClient(
                    limits=httpx.Limits(max_connections=300, max_keepalive_connections=60),
                    timeout=httpx.Timeout(120.0, connect=10.0),
                ),
            ),
        )

    def serves(self, provider_model_id: str) -> bool:
        return provider_model_id in self._model_map

    def backend_model_id(self, provider_model_id: str) -> str:
        return self._model_map[provider_model_id]
