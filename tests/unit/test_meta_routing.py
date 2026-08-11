"""Router-tag resolution + routing-feed reconcile.

The contract: candidate lists come from the catalog feed (one source of truth
with registry/pricing); resolution walks them in priority order and picks the
FIRST candidate this deployment serves — so a single-provider box still
resolves every tag its provider can cover, and 'best' updates are data changes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mlpal_assistants_service.core.exceptions import (
    ModelNotAvailableError,
    ModelNotFoundError,
)
from mlpal_assistants_service.db.models import MetaModelRouting, ModelRegistry
from mlpal_assistants_service.services.catalog_sync import plan_routing
from mlpal_assistants_service.services.router import ModelRouter


# ── plan_routing (feed → table convergence) ──────────────────────────────────


def _feed(candidates: list[str]) -> list[dict]:
    return [{
        "meta_model_tag": "mlpal", "operation": "chat",
        "candidates": [{"model_tag": t, "reason": f"r-{t}"} for t in candidates],
    }]


def test_plan_routing_inserts_ordered_candidates():
    plan = plan_routing([], _feed(["a", "b", "c"]))
    assert [(r["resolved_model_tag"], r["priority"]) for r in plan.upsert] == [
        ("a", 0), ("b", 1), ("c", 2)
    ]
    assert plan.deactivate == []


def test_plan_routing_is_idempotent():
    existing = [
        {"id": i, "meta_model_tag": "mlpal", "operation": "chat",
         "resolved_model_tag": t, "priority": i, "reason": f"r-{t}"}
        for i, t in enumerate(["a", "b"])
    ]
    plan = plan_routing(existing, _feed(["a", "b"]))
    assert plan.upsert == [] and plan.deactivate == []


def test_plan_routing_shrinks_and_replaces():
    existing = [
        {"id": i, "meta_model_tag": "mlpal", "operation": "chat",
         "resolved_model_tag": t, "priority": i, "reason": f"r-{t}"}
        for i, t in enumerate(["old-best", "b", "c"])
    ]
    plan = plan_routing(existing, _feed(["new-best", "b"]))
    # priority 0 replaced, priority 1 unchanged, priority 2 deactivated
    assert [(r["resolved_model_tag"], r["priority"]) for r in plan.upsert] == [("new-best", 0)]
    assert plan.deactivate == [2]


# ── availability-aware resolution ────────────────────────────────────────────


def _routing(tag: str, prio: int) -> MetaModelRouting:
    r = MetaModelRouting()
    r.meta_model_tag = "mlpal"
    r.operation = "chat"
    r.resolved_model_tag = tag
    r.priority = prio
    r.is_active = True
    r.reason = f"r-{tag}"
    return r


def _model(tag: str, provider: str) -> ModelRegistry:
    m = ModelRegistry()
    m.model_tag = tag
    m.provider = provider
    m.provider_model_id = tag
    m.is_active = True
    m.is_deprecated = False
    m.is_paused = False
    m.capabilities = {"operation": "chat"}
    return m


def _router(candidates: list[MetaModelRouting], models: dict[str, ModelRegistry],
            enabled: set[str]) -> ModelRouter:
    router = ModelRouter(MagicMock(), redis_client=None)
    router._meta_routing_repo = MagicMock()
    router._meta_routing_repo.get_candidates = AsyncMock(return_value=candidates)

    async def fake_get_model(tag: str):
        if tag not in models:
            raise ModelNotFoundError(f"Model not found: {tag}")
        return models[tag]

    router.get_model = fake_get_model
    router._adapter_factory = MagicMock()
    router._adapter_factory.is_enabled = lambda p: p in enabled
    return router


@pytest.mark.asyncio
async def test_first_served_candidate_wins():
    router = _router(
        [_routing("gpt-best", 0), _routing("claude-best", 1)],
        {"gpt-best": _model("gpt-best", "openai"), "claude-best": _model("claude-best", "anthropic")},
        enabled={"openai", "anthropic"},
    )
    resolved, meta = await router.resolve_meta_model("mlpal", "chat")
    assert resolved == "gpt-best" and meta.resolved_model == "gpt-best"


@pytest.mark.asyncio
async def test_single_provider_box_falls_through():
    """THE fix: anthropic-only box, best candidate is openai → next served wins."""
    router = _router(
        [_routing("gpt-best", 0), _routing("claude-best", 1)],
        {"gpt-best": _model("gpt-best", "openai"), "claude-best": _model("claude-best", "anthropic")},
        enabled={"anthropic"},
    )
    resolved, _ = await router.resolve_meta_model("mlpal", "chat")
    assert resolved == "claude-best"


@pytest.mark.asyncio
async def test_paused_candidate_is_skipped():
    paused = _model("gpt-best", "openai")
    paused.is_paused = True
    router = _router(
        [_routing("gpt-best", 0), _routing("claude-best", 1)],
        {"gpt-best": paused, "claude-best": _model("claude-best", "anthropic")},
        enabled={"openai", "anthropic"},
    )
    resolved, _ = await router.resolve_meta_model("mlpal", "chat")
    assert resolved == "claude-best"


@pytest.mark.asyncio
async def test_nothing_served_is_a_clear_error():
    router = _router(
        [_routing("gpt-best", 0)],
        {"gpt-best": _model("gpt-best", "openai")},
        enabled=set(),  # no providers configured for these candidates
    )
    with pytest.raises(ModelNotAvailableError) as e:
        await router.resolve_meta_model("mlpal", "chat")
    assert "tried" in str(e.value.details.get("reason", "")) or "tried" in str(e.value)


@pytest.mark.asyncio
async def test_concrete_tags_bypass_routing():
    router = _router([], {}, enabled=set())
    resolved, meta = await router.resolve_meta_model("claude-opus-5", "chat")
    assert resolved == "claude-opus-5" and meta is None
