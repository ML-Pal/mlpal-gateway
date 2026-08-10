"""Usage tracking schemas."""

from datetime import datetime

from pydantic import Field

from mlpal_assistants_service.schemas.common import BaseSchema


class UsageRecord(BaseSchema):
    """A single usage record."""

    trace_id: str = Field(..., description="Unique trace ID")
    model_tag: str = Field(..., description="Model used")
    provider: str = Field(..., description="Provider")
    operation: str = Field(..., description="Operation type")
    input_tokens: int = Field(..., description="Input tokens")
    output_tokens: int = Field(..., description="Output tokens")
    compute_units: float = Field(..., description="Compute units consumed")
    latency_ms: int | None = Field(default=None, description="Request latency")
    status: str = Field(..., description="Request status")
    created_at: datetime = Field(..., description="Timestamp")


class UsageSummary(BaseSchema):
    """Usage summary for a time period."""

    period_start: datetime = Field(..., description="Period start")
    period_end: datetime = Field(..., description="Period end")
    total_requests: int = Field(..., description="Total requests")
    total_input_tokens: int = Field(..., description="Total input tokens")
    total_output_tokens: int = Field(..., description="Total output tokens")
    total_compute_units: float = Field(..., description="Total compute units")
    quota_limit: float = Field(..., description="User's quota limit")
    quota_remaining: float = Field(..., description="Remaining quota")
    by_model: dict[str, "ModelUsage"] = Field(
        default_factory=dict,
        description="Usage breakdown by model",
    )


class ModelUsage(BaseSchema):
    """Usage for a specific model."""

    model_tag: str = Field(..., description="Model identifier")
    requests: int = Field(..., description="Number of requests")
    input_tokens: int = Field(..., description="Input tokens")
    output_tokens: int = Field(..., description="Output tokens")
    compute_units: float = Field(..., description="Compute units")


class UsageListResponse(BaseSchema):
    """Paginated usage records response."""

    items: list[UsageRecord] = Field(..., description="Usage records")
    total: int = Field(..., description="Total records")
    page: int = Field(..., description="Current page")
    page_size: int = Field(..., description="Page size")
    has_more: bool = Field(..., description="More records available")


class DailyUsageBucket(BaseSchema):
    """One day of usage aggregated by ``date_trunc('day', created_at)``."""

    date: str = Field(..., description="ISO date (YYYY-MM-DD) in UTC")
    requests: int = Field(..., description="Requests that day")
    input_tokens: int = Field(..., description="Sum of input tokens that day")
    output_tokens: int = Field(..., description="Sum of output tokens that day")
    compute_units: float = Field(..., description="Sum of compute units that day")


class DailyUsageResponse(BaseSchema):
    """Daily breakdown response — used by both /v1/usage/daily and
    /v1/keys/{id}/usage/daily. Empty days inside the window are not
    materialised (the consumer should zero-fill if a contiguous series
    is needed)."""

    period_start: datetime = Field(..., description="Window start (inclusive)")
    period_end: datetime = Field(..., description="Window end (inclusive)")
    days: int = Field(..., description="Number of days the window spans")
    total_compute_units: float = Field(..., description="Sum across the window")
    daily: list[DailyUsageBucket] = Field(
        default_factory=list,
        description="Days with at least one logged request",
    )
