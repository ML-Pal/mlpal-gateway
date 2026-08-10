"""Reconcile planners: add / update / soft-retire, provenance-scoped, with
effective-dated pricing. Pure logic — no DB."""

from __future__ import annotations

from mlpal_assistants_service.services.catalog_sync import (
    FEED_SOURCE,
    LOCAL_SOURCE,
    plan_pricing,
    plan_registry,
)


def _model(tag, source=FEED_SOURCE, **over):
    row = {
        "model_tag": tag, "source": source, "provider": "openai",
        "provider_model_id": tag, "display_name": tag, "description": None,
        "capabilities": {"tools": True}, "context_length": 128000,
        "max_output_tokens": 8192, "pricing_tier": "standard",
        "fallback_model_tag": None, "priority": 100, "is_active": True,
        "is_deprecated": False, "deprecation_message": None, "is_paused": False,
        "pause_reason": None,
    }
    row.update(over)
    return row


# ── registry ─────────────────────────────────────────────────────────────────


def test_insert_new_model():
    plan = plan_registry(existing=[], feed=[_model("gpt-x")])
    assert [r["model_tag"] for r in plan.insert] == ["gpt-x"]
    assert not plan.update and not plan.retire


def test_update_changed_field_only():
    existing = [_model("gpt-x", context_length=128000)]
    feed = [_model("gpt-x", context_length=200000, display_name="gpt-x")]
    plan = plan_registry(existing, feed)
    assert plan.insert == [] and plan.retire == []
    assert plan.update == [{"model_tag": "gpt-x", "changes": {"context_length": 200000}}]


def test_unchanged_is_noop():
    m = _model("gpt-x")
    assert plan_registry(existing=[m], feed=[_model("gpt-x")]).is_empty


def test_feed_owned_absent_is_soft_retired():
    plan = plan_registry(existing=[_model("old")], feed=[])
    assert plan.retire == ["old"]


def test_already_retired_is_not_retired_again():
    retired = _model("old", is_active=False, is_deprecated=True)
    assert plan_registry(existing=[retired], feed=[]).is_empty


def test_local_model_never_touched():
    # absent from feed → NOT retired; present in feed with changes → NOT updated.
    local_absent = _model("my-ft", source=LOCAL_SOURCE)
    local_shadow = _model("gpt-x", source=LOCAL_SOURCE, context_length=1)
    feed = [_model("gpt-x", context_length=999999)]  # would-be update, but it's local
    plan = plan_registry(existing=[local_absent, local_shadow], feed=feed)
    assert plan.retire == []          # local_absent left alone
    assert plan.update == []          # local_shadow not updated by the feed
    assert plan.insert == []          # gpt-x already exists (as local)


def test_retired_feed_model_returns_and_is_reactivated():
    was_retired = _model("gpt-x", is_active=False, is_deprecated=True,
                         deprecation_message="gone")
    feed = [_model("gpt-x", is_active=True, is_deprecated=False, deprecation_message=None)]
    plan = plan_registry(existing=[was_retired], feed=feed)
    changes = plan.update[0]["changes"]
    assert changes["is_active"] is True and changes["is_deprecated"] is False


# ── pricing (effective-dated) ────────────────────────────────────────────────


def _price(tag, op="chat", **over):
    row = {"model_tag": tag, "operation": op, "tier": "standard",
           "input_rate": "1.00", "output_rate": "2.00", "rate_unit": "per_1m",
           "markup_multiplier": "3.00", "cu_to_dollar": "0.1",
           "input_cu_rate": "10", "output_cu_rate": "20"}
    row.update(over)
    return row


def test_new_price_is_activated():
    plan = plan_pricing(existing_active=[], feed=[_price("gpt-x")])
    assert len(plan.activate) == 1 and plan.deactivate == []


def test_changed_price_supersedes_old():
    existing = [_price("gpt-x", input_rate="1.00")]
    feed = [_price("gpt-x", input_rate="1.50")]
    plan = plan_pricing(existing, feed)
    assert plan.activate[0]["input_rate"] == "1.50"
    assert plan.deactivate == [("gpt-x", "chat")]


def test_dirty_feed_duplicate_key_keeps_latest_effective_date():
    # A live dump can carry a superseded row that was never deactivated; the
    # planner must keep only the latest per (tag, op) — not insert both.
    feed = [
        _price("gem", input_rate="0.075", effective_date="2026-06-21"),
        _price("gem", input_rate="0.25", effective_date="2026-07-27"),
    ]
    plan = plan_pricing(existing_active=[], feed=feed)
    assert len(plan.activate) == 1
    assert plan.activate[0]["input_rate"] == "0.25"


def test_unchanged_price_is_noop_across_decimal_forms():
    # "3.00" (feed) vs Decimal 3 (db) must compare equal → no churn.
    existing = [_price("gpt-x", markup_multiplier=3, input_rate=1, output_rate=2,
                       cu_to_dollar=0.1, input_cu_rate=10, output_cu_rate=20)]
    feed = [_price("gpt-x")]  # string forms of the same numbers
    assert plan_pricing(existing, feed).is_empty
