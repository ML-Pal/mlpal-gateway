"""P0 #3 provider activation: with only some provider keys present, the served
catalog is filtered to enabled providers and disabled-provider models 404 with a
clean reason instead of a provider-init 5xx. No-op when all keys are set (prod)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mlpal_assistants_service.core.exceptions import ModelNotAvailableError
from mlpal_assistants_service.services.router import ModelRouter

# only OpenAI configured (anthropic/google/bedrock absent) — OSS single-provider case
_BACKEND_DEFAULTS = {
    "openai_backends": "first_party", "google_backends": "first_party",
    "anthropic_backends": "first_party", "azure_openai_endpoint": None,
    "azure_openai_api_key": None, "azure_openai_deployments": None,
    "vertex_project": None, "bedrock_anthropic_models": None,
    "vertex_anthropic_models": None,
}
_ONE_KEY = SimpleNamespace(openai_api_key="k", anthropic_api_key=None,
                           google_api_key=None, enable_bedrock=False,
                           **_BACKEND_DEFAULTS)


def _models():
    return [
        SimpleNamespace(provider="openai", model_tag="gpt-x", is_paused=False),
        SimpleNamespace(provider="anthropic", model_tag="claude-x", is_paused=False),
        SimpleNamespace(provider="google", model_tag="gemini-x", is_paused=False),
    ]


def test_list_filters_to_enabled_providers():
    with patch("mlpal_assistants_service.adapters.factory.get_settings", return_value=_ONE_KEY):
        served = ModelRouter._filter_enabled(_models())
    assert [m.model_tag for m in served] == ["gpt-x"]  # only the provider we have a key for


def test_get_model_gate_404s_disabled_provider_but_allows_enabled():
    with patch("mlpal_assistants_service.adapters.factory.get_settings", return_value=_ONE_KEY):
        # disabled provider → clean ModelNotAvailableError (not a 5xx at adapter init)
        with pytest.raises(ModelNotAvailableError) as ei:
            ModelRouter._raise_if_paused("claude-x", SimpleNamespace(
                provider="anthropic", model_tag="claude-x", is_paused=False))
        assert "not configured" in (ei.value.reason or "")
        # enabled provider passes the gate
        ModelRouter._raise_if_paused("gpt-x", SimpleNamespace(
            provider="openai", model_tag="gpt-x", is_paused=False))


def test_no_filtering_when_all_providers_enabled():
    all_keys = SimpleNamespace(openai_api_key="a", anthropic_api_key="b",
                               google_api_key="c", enable_bedrock=True,
                               **_BACKEND_DEFAULTS)
    with patch("mlpal_assistants_service.adapters.factory.get_settings", return_value=all_keys):
        served = ModelRouter._filter_enabled(_models())
    assert len(served) == 3  # prod: nothing filtered


def test_meta_models_always_served():
    # meta-models (provider 'mlpal') are routing aliases — never filtered by
    # provider-key gating; their servability is decided at resolution time.
    metas = [SimpleNamespace(provider="mlpal", model_tag="mlpal", is_paused=False),
             SimpleNamespace(provider="mlpal", model_tag="mlpal-lite", is_paused=False)]
    with patch("mlpal_assistants_service.adapters.factory.get_settings", return_value=_ONE_KEY):
        assert len(ModelRouter._filter_enabled(metas)) == 2
        ModelRouter._raise_if_paused("mlpal", metas[0])  # gate must not reject a meta-model


def test_bedrock_gated_by_enable_flag():
    bedrock_model = [SimpleNamespace(provider="bedrock", model_tag="kimi-k2.5", is_paused=False)]
    off = SimpleNamespace(openai_api_key="k", anthropic_api_key=None,
                          google_api_key=None, enable_bedrock=False)
    on = SimpleNamespace(openai_api_key="k", anthropic_api_key=None,
                         google_api_key=None, enable_bedrock=True)
    with patch("mlpal_assistants_service.adapters.factory.get_settings", return_value=off):
        assert ModelRouter._filter_enabled(bedrock_model) == []  # no AWS → hidden
    with patch("mlpal_assistants_service.adapters.factory.get_settings", return_value=on):
        assert len(ModelRouter._filter_enabled(bedrock_model)) == 1
