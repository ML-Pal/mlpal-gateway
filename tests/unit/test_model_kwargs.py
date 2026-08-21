"""model_kwargs: pass-through with LOUD rejection (never silent drops).

Contract (planning/research/openrouter-feature-map.md, non-negotiable #2):
provider-native params ride an explicit field on both wires; keys the serving
adapter can't take are rejected with a 400 that lists them and the supported
set, before any provider call. Reserved gateway-owned fields are rejected on
every adapter, including accept-all ones (bedrock, byom).
"""

from __future__ import annotations

import pytest

from mlpal_assistants_service.adapters.anthropic import AnthropicAdapter
from mlpal_assistants_service.adapters.bedrock import BedrockAdapter
from mlpal_assistants_service.adapters.google import GoogleAdapter
from mlpal_assistants_service.adapters.openai import OpenAIAdapter
from mlpal_assistants_service.core.exceptions import UnsupportedModelKwargsError
from mlpal_assistants_service.services.messages_v2.schemas import (
    InvalidMessagesRequest,
    validate,
)


def _openai():
    return OpenAIAdapter.__new__(OpenAIAdapter)  # no client needed for validation


def test_unknown_keys_rejected_with_full_listing():
    a = _openai()
    with pytest.raises(UnsupportedModelKwargsError) as exc:
        a.validate_model_kwargs({"logit_bias": {"50256": -100}, "seed": 7})
    assert exc.value.offending == ["logit_bias", "seed"]
    assert "reasoning" in exc.value.allowed  # the supported set is named
    assert "Nothing was sent to the provider" in exc.value.message


def test_supported_keys_pass():
    _openai().validate_model_kwargs({"reasoning": {"effort": "low"}, "service_tier": "flex"})


def test_reserved_keys_always_rejected_even_on_accept_all():
    b = BedrockAdapter.__new__(BedrockAdapter)
    assert b.accept_all_kwargs is True
    b.validate_model_kwargs({"top_k": 5, "anything_goes": 1})  # arbitrary ok
    with pytest.raises(UnsupportedModelKwargsError) as exc:
        b.validate_model_kwargs({"model": "evil", "top_k": 5})
    assert exc.value.offending == ["model"]


def test_byom_instance_accepts_arbitrary_but_not_reserved():
    a = _openai()
    a.accept_all_kwargs = True  # what connections._build_adapter sets for byom
    a.validate_model_kwargs({"vllm_specific_thing": True})
    with pytest.raises(UnsupportedModelKwargsError):
        a.validate_model_kwargs({"messages": []})


def test_empty_and_none_are_noops():
    _openai().validate_model_kwargs(None)
    _openai().validate_model_kwargs({})


def test_each_adapter_declares_a_curated_surface():
    assert "reasoning" in OpenAIAdapter.SUPPORTED_KWARGS
    assert "top_k" in AnthropicAdapter.SUPPORTED_KWARGS
    assert "safety_settings" in GoogleAdapter.SUPPORTED_KWARGS
    # reserved list can never leak into a supported list
    for cls in (OpenAIAdapter, AnthropicAdapter, GoogleAdapter):
        assert not (cls.SUPPORTED_KWARGS & cls.RESERVED_KWARGS)


def test_v2_validate_pops_model_kwargs_from_body():
    req = validate(
        b'{"model":"claude-sonnet-5","messages":[],"model_kwargs":{"top_k":3}}'
    )
    assert req.model_kwargs == {"top_k": 3}
    assert "model_kwargs" not in req.body  # never forwarded as a wire field


def test_v2_validate_rejects_non_object_model_kwargs():
    with pytest.raises(InvalidMessagesRequest):
        validate(b'{"model":"m","messages":[],"model_kwargs":"nope"}')


# ── byom wire mode: chat_completions dialect ────────────────────────────────


def test_byom_wire_is_chat_completions():
    """byom endpoints speak /v1/chat/completions (vLLM/Ollama/TGI standard) —
    the Responses API is OpenAI-first-party/Azure only."""
    assert OpenAIAdapter.wire == "responses"  # class default untouched
    a = OpenAIAdapter.__new__(OpenAIAdapter)
    a.wire = "chat_completions"  # what connections._build_adapter sets
    params = a._completions_params(
        "m", [{"role": "user", "content": "hi", "files": ["x"]}],
        0.7, 50, None, None, None, None, None, {"custom_knob": 1},
    )
    assert params["messages"] == [{"role": "user", "content": "hi"}]  # gateway keys stripped
    assert params["max_tokens"] == 50
    assert params["extra_body"] == {"custom_knob": 1}


@pytest.mark.asyncio
async def test_completions_compat_loop_renames_and_drops_on_provider_complaint():
    """OpenAI reasoning models demand max_completion_tokens + pinned
    temperature; the compat loop reacts ONLY to the provider's own param
    complaint and never touches anything else."""

    class _Err(Exception):
        def __init__(self, param, msg):
            super().__init__(msg)
            self.body = {"error": {"param": param}}

    calls = []

    class _FakeCompletions:
        async def create(self, **params):
            calls.append(dict(params))
            if "max_tokens" in params:
                raise _Err("max_tokens", "use 'max_completion_tokens' instead")
            if "temperature" in params:
                raise _Err("temperature", "does not support 0.7")
            return "ok"

    a = OpenAIAdapter.__new__(OpenAIAdapter)
    a._client = type("C", (), {"chat": type("Ch", (), {"completions": _FakeCompletions()})()})()
    result = await a._create_completions({"model": "m", "max_tokens": 5, "temperature": 0.7})
    assert result == "ok"
    assert "max_completion_tokens" in calls[-1] and "temperature" not in calls[-1]
    # an unrelated error re-raises untouched
    class _Boom:
        async def create(self, **params):
            raise RuntimeError("unrelated")
    a._client = type("C", (), {"chat": type("Ch", (), {"completions": _Boom()})()})()
    with pytest.raises(RuntimeError):
        await a._create_completions({"model": "m"})
