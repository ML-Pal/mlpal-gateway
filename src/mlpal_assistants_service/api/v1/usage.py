"""Usage tracking endpoints."""

from datetime import datetime

from fastapi import APIRouter, Query

from mlpal_assistants_service.api.deps import CurrentUserFlexible, UsageServiceDep
from mlpal_assistants_service.schemas.usage import DailyUsageResponse, UsageSummary

router = APIRouter()


@router.get(
    "/summary",
    response_model=UsageSummary,
    summary="Get usage summary",
    description="Get usage summary for the current billing period.",
)
async def get_usage_summary(
    user_id: CurrentUserFlexible,
    usage_service: UsageServiceDep,
    start_date: datetime | None = Query(
        default=None,
        description="Start date for the summary period",
    ),
    end_date: datetime | None = Query(
        default=None,
        description="End date for the summary period",
    ),
) -> UsageSummary:
    """
    Get usage summary for a time period.

    Accepts either API key or JWT authentication.
    Defaults to current month if no dates specified.
    """
    # Default to current month
    if start_date is None:
        start_date = datetime.utcnow().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
    if end_date is None:
        end_date = datetime.utcnow()

    summary = await usage_service.get_usage_summary(
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
    )

    return UsageSummary(
        period_start=summary["period_start"],
        period_end=summary["period_end"],
        total_requests=summary["total_requests"],
        total_input_tokens=summary["total_input_tokens"],
        total_output_tokens=summary["total_output_tokens"],
        total_compute_units=summary["total_compute_units"],
        quota_limit=summary["quota_limit"],
        quota_remaining=summary["quota_remaining"],
        by_model=summary["by_model"],
    )


@router.get(
    "/daily",
    response_model=DailyUsageResponse,
    summary="Get daily usage",
    description=(
        "Daily compute-unit + token breakdown for the calling user over the "
        "requested window (default 30 days, max 90). Days with no logged "
        "requests are omitted from the response; zero-fill in the consumer "
        "if a contiguous series is needed."
    ),
)
async def get_daily_usage(
    user_id: CurrentUserFlexible,
    usage_service: UsageServiceDep,
    days: int = Query(default=30, ge=1, le=90, description="Number of days"),
) -> DailyUsageResponse:
    """Daily breakdown by user. JWT or API key auth."""
    result = await usage_service.get_usage_daily(user_id=user_id, days=days)
    return DailyUsageResponse(**result)
