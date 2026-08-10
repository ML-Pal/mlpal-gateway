"""API Key schemas."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from mlpal_assistants_service.schemas.common import BaseSchema

BudgetUnit = Literal["usd", "cu"]
BudgetWindow = Literal["daily", "weekly", "monthly", "lifetime"]


class ModelPolicy(BaseSchema):
    """Per-key model access control. Glob patterns; ``*``/empty allow = all;
    deny (union) wins. Applied to the requested tag and the resolved model."""

    allow: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Allowed model tags/globs, e.g. ['gpt-5.6-*', 'claude-opus-5']. ['*'] = all.",
    )
    deny: list[str] = Field(
        default_factory=list,
        description="Denied model tags/globs; takes precedence over allow.",
    )


class BudgetRule(BaseSchema):
    """A single spend cap. All of a key's rules are enforced (deny if ANY window
    is exhausted). ``amount`` is in ``unit``; a request is denied once spend for
    ``window`` reaches it."""

    id: str | None = Field(default=None, max_length=64, description="Optional label for this rule.")
    unit: BudgetUnit = Field(..., description="'usd' or 'cu' (compute units).")
    amount: float = Field(..., gt=0, description="Cap amount in `unit`.")
    window: BudgetWindow = Field(
        ...,
        description="'daily'|'weekly'|'monthly' (calendar-aligned) or 'lifetime' (never resets).",
    )


class APIKeyCreate(BaseSchema):
    """Request schema for creating an API key."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Name for the API key",
        examples=["Production Key", "Development Key"],
    )
    description: str | None = Field(
        default=None,
        max_length=500,
        description="Optional description",
    )
    permissions: list[str] = Field(
        default=["*"],
        description="Allowed operations (e.g., ['chat', 'embeddings'] or ['*'] for all)",
    )
    expires_at: datetime | None = Field(
        default=None,
        description=(
            "Optional expiration date. `null` means the key never expires — "
            "intended for service-bound keys whose lifecycle is owned by the "
            "calling service (revocation, not expiry, is the kill switch)."
        ),
    )
    tags: dict | None = Field(
        default=None,
        description=(
            "Free-form attribution tags. Service callers tag keys with the "
            "entity that owns them (e.g., "
            '`{"mcp_server_id": 18, "cde_id": 9, "source": "mcp_builder_cde"}`).'
        ),
    )
    model_policy: ModelPolicy | None = Field(
        default=None,
        description="Model access control. Omit/null = unrestricted (all served models).",
    )
    budgets: list[BudgetRule] | None = Field(
        default=None,
        description="Spend caps. Omit/null = no per-key budget. At most one rule per window.",
    )

    @field_validator("budgets")
    @classmethod
    def _one_rule_per_window(cls, v: list[BudgetRule] | None) -> list[BudgetRule] | None:
        if v:
            windows = [b.window for b in v]
            if len(windows) != len(set(windows)):
                raise ValueError("at most one budget rule per window (daily/weekly/monthly/lifetime)")
        return v


class APIKeyUpdate(BaseSchema):
    """Patch a key's policy in place. Only provided fields change; pass an empty
    object/list to clear. `None`/omitted leaves the field untouched — so we use a
    sentinel-free convention: send `model_policy: {}` to clear, omit to keep."""

    model_policy: ModelPolicy | None = Field(default=None, description="Replace model access policy.")
    budgets: list[BudgetRule] | None = Field(default=None, description="Replace spend budgets.")

    @field_validator("budgets")
    @classmethod
    def _one_rule_per_window(cls, v: list[BudgetRule] | None) -> list[BudgetRule] | None:
        return APIKeyCreate._one_rule_per_window.__func__(cls, v)  # type: ignore[attr-defined]


class APIKeyResponse(BaseSchema):
    """Response schema for an API key (without the secret)."""

    id: int = Field(..., description="Unique key ID")
    name: str = Field(..., description="Key name")
    description: str | None = Field(default=None, description="Key description")
    key_prefix: str = Field(..., description="Key prefix for identification")
    permissions: list[str] = Field(..., description="Allowed operations")
    rate_limit_tier: str = Field(..., description="Rate limit tier")

    @field_validator("permissions", mode="before")
    @classmethod
    def _permissions_to_list(cls, v: object) -> object:
        """Tolerate the legacy dict form ({"admin": true, "*": true}) some
        bootstrap keys stored — one dict-form key must not 500 the whole list
        (has_permission accepts both shapes; the wire always serializes a list)."""
        if isinstance(v, dict):
            return [k for k, granted in v.items() if granted]
        return v
    is_active: bool = Field(..., description="Whether key is active")
    last_used_at: datetime | None = Field(default=None, description="Last usage timestamp")
    expires_at: datetime | None = Field(default=None, description="Expiration date")
    created_at: datetime = Field(..., description="Creation timestamp")
    model_policy: dict | None = Field(default=None, description="Model access policy (null = unrestricted)")
    budgets: list[dict] | None = Field(default=None, description="Spend budgets (null = none)")


class APIKeyWithSecret(APIKeyResponse):
    """
    Response schema for newly created API key (includes the secret).

    The secret is only returned once during creation.
    """

    secret: str = Field(
        ...,
        description="The API key secret. Save this - it won't be shown again!",
    )


class APIKeyList(BaseSchema):
    """Response schema for listing API keys."""

    items: list[APIKeyResponse] = Field(..., description="List of API keys")
    total: int = Field(..., description="Total number of keys")


class KeyUsageSummary(BaseSchema):
    """Per-key usage summary.

    Differs from ``UsageSummary`` (in ``schemas/usage.py``) by intent rather
    than by shape: quotas are a user-level concept, not a per-key one, so
    this schema has no ``quota_limit`` / ``quota_remaining``. Adds explicit
    success/error counts which are far more useful at the key granularity.
    """

    api_key_id: int = Field(..., description="The API key this summary covers")
    period_start: datetime = Field(..., description="Aggregation window start")
    period_end: datetime = Field(..., description="Aggregation window end")
    total_requests: int = Field(..., description="Total requests in the window")
    success_requests: int = Field(..., description="Requests with status='success'")
    error_requests: int = Field(..., description="Requests with status<>'success'")
    total_input_tokens: int = Field(..., description="Sum of input tokens")
    total_output_tokens: int = Field(..., description="Sum of output tokens")
    total_compute_units: float = Field(..., description="Sum of compute units consumed")
    last_used_at: datetime | None = Field(default=None, description="Most recent usage timestamp")
