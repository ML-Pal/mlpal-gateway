"""Reasoning normalization for /v2/messages translation edges.

Anthropic's Messages API expresses extended thinking as a token budget
(`thinking: {type: "enabled", budget_tokens: N}`); OpenAI/Google express it as
an ordinal effort. We normalize the budget to a provider-neutral effort tier so
a single inbound surface maps cleanly onto either backend. This is captured for
observability (usage logs) even where the underlying adapter call doesn't yet
take an explicit effort knob — so the requested effort is never silently lost.
"""

from __future__ import annotations

# Provider-neutral ordinal effort tiers (low → high).
_LOW = "low"
_MEDIUM = "medium"
_HIGH = "high"

# Anthropic budget_tokens thresholds → effort tier. The cutoffs mirror the
# rough bands the major providers use for minimal/standard/deep reasoning.
_MEDIUM_FLOOR = 4096
_HIGH_FLOOR = 16384


def effort_from_thinking(thinking: dict | None) -> str | None:
    """Map an Anthropic `thinking` block to a normalized effort tier.

    Returns None when thinking is absent or explicitly disabled (let the model
    use its own default), else one of "low" | "medium" | "high".
    """
    if not isinstance(thinking, dict):
        return None
    if thinking.get("type") != "enabled":
        return None
    budget = thinking.get("budget_tokens")
    if not isinstance(budget, int) or budget <= 0:
        return _MEDIUM  # enabled without a usable budget → standard effort
    if budget >= _HIGH_FLOOR:
        return _HIGH
    if budget >= _MEDIUM_FLOOR:
        return _MEDIUM
    return _LOW
