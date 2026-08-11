"""Tests for model pause enforcement and the newest-model sampling-param gates.

- A paused model is registered but must not be served: get_model raises
  ModelNotAvailableError (which the API maps to 503), even from cache.
- The newest OpenAI (gpt-5.5) and Anthropic (opus-4-7/4-8, fable-5) models
  reject `temperature`; the adapters must skip it for those (verified against
  the live APIs).
"""

from unittest.mock import MagicMock

import pytest

from mlpal_assistants_service.adapters.anthropic import AnthropicAdapter
from mlpal_assistants_service.adapters.openai import OpenAIAdapter
from mlpal_assistants_service.core.exceptions import ModelNotAvailableError
from mlpal_assistants_service.db.models import ModelRegistry
from mlpal_assistants_service.services.router import ModelRouter


def _router() -> ModelRouter:
    return ModelRouter(MagicMock(), redis_client=None)


def _model(**kw) -> ModelRegistry:
    base = dict(  # noqa: C408 — kwargs-style keeps the field list diffable
        model_tag="m",
        provider="anthropic",
        provider_model_id="m",
        display_name="M",
        capabilities={"operation": "chat"},
        is_active=True,
        is_deprecated=False,
        is_paused=False,
        pause_reason=None,
    )
    base.update(kw)
    return ModelRegistry(**base)


class TestPauseEnforcement:
    def test_raise_if_paused_raises_with_reason(self):
        m = _model(model_tag="claude-fable-5", is_paused=True, pause_reason="Suspended by Anthropic")
        with pytest.raises(ModelNotAvailableError) as exc:
            ModelRouter._raise_if_paused("claude-fable-5", m)
        assert exc.value.reason == "Suspended by Anthropic"

    def test_raise_if_paused_noop_when_not_paused(self):
        ModelRouter._raise_if_paused("m", _model(is_paused=False))  # must not raise

    @pytest.mark.asyncio
    async def test_get_model_rejects_paused_from_cache(self):
        router = _router()
        await router._local_cache.set(
            "claude-fable-5",
            _model(model_tag="claude-fable-5", is_paused=True, pause_reason="paused"),
        )
        with pytest.raises(ModelNotAvailableError):
            await router.get_model("claude-fable-5")

    def test_pause_state_survives_cache_serialization(self):
        router = _router()
        paused = _model(model_tag="claude-fable-5", is_paused=True, pause_reason="paused")
        copy = router._detached_model(paused)
        assert copy.is_paused is True
        assert copy.pause_reason == "paused"


class TestOpenAISamplingGate:
    @pytest.fixture
    def adapter(self):
        return OpenAIAdapter(api_key="test")

    @pytest.mark.parametrize("model", ["gpt-5.5", "gpt-5.5-pro", "gpt-5.4-pro", "gpt-5-nano", "o3"])
    def test_skips_temperature(self, adapter, model):
        assert adapter._model_skips_sampling_params(model) is True

    @pytest.mark.parametrize("model", ["gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-4o"])
    def test_keeps_temperature(self, adapter, model):
        assert adapter._model_skips_sampling_params(model) is False


class TestAnthropicTemperatureGate:
    @pytest.fixture
    def adapter(self):
        return AnthropicAdapter(api_key="test")

    @pytest.mark.parametrize(
        "model", ["claude-opus-4-7", "claude-opus-4-8", "claude-fable-5", "claude-mythos-5"]
    )
    def test_skips_temperature(self, adapter, model):
        assert adapter._skips_temperature(model) is True

    @pytest.mark.parametrize(
        "model", ["claude-sonnet-4-6", "claude-opus-4-6", "claude-opus-4-5-20251101"]
    )
    def test_keeps_temperature(self, adapter, model):
        assert adapter._skips_temperature(model) is False
