"""Account-scoped platform views: /v1/account/providers.

The Models-tab status strip: one row per catalog provider family with live
platform health and the caller's BYOK connection state. Read-only; byom
endpoints don't map to a catalog family and live only in /v1/connections.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from mlpal_assistants_service.api.deps import ManagementPrincipal, ModelRouterDep
from mlpal_assistants_service.api.v1.connections import _require_enabled
from mlpal_assistants_service.db.models import ModelRegistry
from mlpal_assistants_service.db.models.usage_log import UsageLog

router = APIRouter()

DISPLAY_NAMES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "bedrock": "AWS Bedrock",
}

# platform_status is derived from the last 10 minutes of THIS deployment's
# usage_logs — real serving outcomes, no per-request provider I/O. Below
# MIN_SAMPLE requests the window is too thin to accuse anyone: operational.
STATUS_WINDOW = timedelta(minutes=10)
MIN_SAMPLE = 5
DEGRADED_ERROR_RATE = 0.10
DOWN_ERROR_RATE = 0.50


def _status(total: int, errors: int) -> str:
    if total < MIN_SAMPLE:
        return "operational"
    rate = errors / total
    if rate >= DOWN_ERROR_RATE:
        return "down"
    if rate >= DEGRADED_ERROR_RATE:
        return "degraded"
    return "operational"


@router.get("/providers", summary="Provider status board (Models-tab strip)")
async def account_providers(
    principal: ManagementPrincipal, model_router: ModelRouterDep
) -> dict:
    _require_enabled()
    session = model_router.session

    served = (
        await session.execute(
            select(ModelRegistry.provider, func.count())
            .where(ModelRegistry.is_active.is_(True))
            .group_by(ModelRegistry.provider)
        )
    ).all()

    since = datetime.now(UTC) - STATUS_WINDOW
    health = {
        row.provider: (row.total, row.errors)
        for row in (
            await session.execute(
                select(
                    UsageLog.provider,
                    func.count().label("total"),
                    func.count()
                    .filter(UsageLog.status != "success")
                    .label("errors"),
                )
                .where(UsageLog.created_at >= since)
                .group_by(UsageLog.provider)
            )
        ).all()
    }

    from mlpal_assistants_service.services import connections as conn_svc

    overlay = await conn_svc.get_overlay(principal.id, session)

    data = []
    for provider, count in sorted(served, key=lambda r: r[0]):
        conns = overlay.get(provider, [])
        if any(c.status == "verified" for c in conns):
            connection = "byok_verified"
        elif any(c.status == "invalid" for c in conns):
            connection = "byok_invalid"
        else:
            connection = "none"
        total, errors = health.get(provider, (0, 0))
        data.append(
            {
                "family": provider,
                "display_name": DISPLAY_NAMES.get(provider, provider.title()),
                "platform_status": _status(total, errors),
                "connection": connection,
                "models_served": count,
            }
        )
    return {"data": data}
