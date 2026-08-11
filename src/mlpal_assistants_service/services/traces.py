"""Shared trace query + serialization.

One implementation behind two doors: the operator door (`/admin/v1/traces`,
global, admin-permission key) and the self-service door (`/v1/usage/traces`,
ALWAYS scoped to the calling principal's user_id). The scoping rule lives here
so the two can never drift: pass `user_id=None` only from the admin surface.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from mlpal_assistants_service.db.models import APIKey
from mlpal_assistants_service.db.models.usage_log import UsageLog


def serialize_trace(r: UsageLog, key_names: dict[int, str] | None = None) -> dict:
    """One trace row, identical shape on both surfaces. `api` is the mount that
    served the call (v1_messages / v2_messages / None for v1 JSON endpoints)."""
    meta = r.cc_metadata or {}
    return {
        "trace_id": r.trace_id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "api_key_id": r.api_key_id,
        "api_key_name": (key_names or {}).get(r.api_key_id),
        "model_tag": r.model_tag,
        "requested_model": meta.get("requested_model"),  # set when a router tag resolved
        "provider": r.provider,
        "operation": r.operation,
        "api": meta.get("api"),
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "compute_units": float(r.compute_units) if r.compute_units is not None else 0.0,
        "latency_ms": r.latency_ms,
        "status": r.status,
        "error_code": r.error_code,
        "metadata": meta,
    }


async def query_traces(
    session: Any,
    *,
    user_id: int | None,
    status: str | None = None,
    model_tag: str | None = None,
    operation: str | None = None,
    api: str | None = None,
    api_key_id: int | None = None,
    trace_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Newest-first trace page + total. `user_id` is the tenancy boundary:
    when set, every condition is ANDed with it — an `api_key_id` belonging to
    another user simply yields an empty page (no ownership oracle)."""
    conditions = []
    if user_id is not None:
        conditions.append(UsageLog.user_id == user_id)
    if since is not None:
        conditions.append(UsageLog.created_at >= since)
    if until is not None:
        conditions.append(UsageLog.created_at <= until)
    if status:
        conditions.append(UsageLog.status == status)
    if model_tag:
        conditions.append(UsageLog.model_tag == model_tag)
    if operation:
        conditions.append(UsageLog.operation == operation)
    if api:
        conditions.append(UsageLog.cc_metadata["api"].as_string() == api)
    if api_key_id is not None:
        conditions.append(UsageLog.api_key_id == api_key_id)
    if trace_id:
        conditions.append(UsageLog.trace_id == trace_id)

    total = (
        await session.execute(select(func.count()).select_from(UsageLog).where(*conditions))
    ).scalar_one()
    rows = (
        await session.execute(
            select(UsageLog)
            .where(*conditions)
            .order_by(UsageLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    # Key names for display (people think in key names, not ids).
    key_names: dict[int, str] = {}
    key_ids = {r.api_key_id for r in rows if r.api_key_id is not None}
    if key_ids:
        for kid, name in (
            await session.execute(select(APIKey.id, APIKey.name).where(APIKey.id.in_(key_ids)))
        ).all():
            key_names[kid] = name

    return {
        "data": [serialize_trace(r, key_names) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def window_from_days(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)
