"""Admin endpoints for cache management.

These endpoints require an API key with 'admin' permission.
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select, update

from mlpal_assistants_service.api.deps import (
    CacheInvalidatorDep,
    CurrentAPIKey,
    ModelRouterDep,
    PricingServiceDep,
    RedisDep,
)
from mlpal_assistants_service.db.models import MetaModelRouting, ModelRegistry
from mlpal_assistants_service.db.models.model_pricing import ModelPricing
from mlpal_assistants_service.services.catalog import load_curated
from mlpal_assistants_service.services.traces import query_traces

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_TARGETS = {"models", "pricing", "routing", "api_keys", "all"}


class CacheInvalidateRequest(BaseModel):
    """Request body for cache invalidation."""

    target: Literal["models", "pricing", "routing", "api_keys", "all"]


class CacheInvalidateResponse(BaseModel):
    """Response for cache invalidation."""

    cleared: str
    instances_notified: bool


class CacheStatusResponse(BaseModel):
    """Response for cache status."""

    model_cache: dict
    routing_cache: dict
    pricing_cache: dict


class ModelPauseRequest(BaseModel):
    """Request body for pausing/unpausing a model."""

    paused: bool
    reason: str | None = None


class ModelPauseResponse(BaseModel):
    """Response for a model pause/unpause."""

    model_tag: str
    paused: bool
    reason: str | None
    instances_notified: bool


def _require_admin(api_key: CurrentAPIKey) -> None:
    """Check that the API key has admin permission."""
    if not api_key.has_permission("admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permission required for cache management",
        )


@router.post(
    "/cache/invalidate",
    response_model=CacheInvalidateResponse,
    summary="Invalidate caches",
    description="Clear caches across all instances. Requires admin permission.",
)
async def invalidate_cache(
    body: CacheInvalidateRequest,
    api_key: CurrentAPIKey,
    cache_invalidator: CacheInvalidatorDep,
    model_router: ModelRouterDep,
    pricing_service: PricingServiceDep,
    redis_client: RedisDep,
) -> CacheInvalidateResponse:
    """Invalidate caches by target.

    Clears the local cache on this instance and publishes a Pub/Sub message
    so other instances clear their local caches too.
    """
    _require_admin(api_key)

    target = body.target

    # Clear local caches on this instance
    if target in ("models", "all"):
        await model_router.clear_all_caches()
    if target in ("pricing", "all"):
        await pricing_service.clear_all_caches()
    if target in ("routing", "all"):
        await model_router._routing_cache.clear()
    if target in ("api_keys", "all"):
        # Clear all auth: keys from Redis
        if redis_client:
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(cursor, match="auth:*", count=100)
                if keys:
                    await redis_client.delete(*keys)
                if cursor == 0:
                    break

    # Publish invalidation to other instances via Pub/Sub
    instances_notified = False
    if cache_invalidator:
        await cache_invalidator.publish(target)
        instances_notified = True

    logger.info("Cache invalidated via admin API", extra={"target": target})

    return CacheInvalidateResponse(
        cleared=target,
        instances_notified=instances_notified,
    )


@router.post(
    "/models/{model_tag}/pause",
    response_model=ModelPauseResponse,
    summary="Pause or unpause a model",
    description=(
        "Pause a model (registered + visible but temporarily not callable, e.g. "
        "an upstream provider suspended it) or unpause it. Requires admin permission. "
        "Send {\"paused\": true, \"reason\": \"...\"} to pause, {\"paused\": false} to resume."
    ),
)
async def set_model_pause(
    model_tag: str,
    body: ModelPauseRequest,
    api_key: CurrentAPIKey,
    model_router: ModelRouterDep,
    cache_invalidator: CacheInvalidatorDep,
) -> ModelPauseResponse:
    """Set a model's paused state and invalidate the model cache everywhere."""
    _require_admin(api_key)

    reason = body.reason if body.paused else None
    result = await model_router.session.execute(
        update(ModelRegistry)
        .where(ModelRegistry.model_tag == model_tag)
        .values(is_paused=body.paused, pause_reason=reason)
        .returning(ModelRegistry.model_tag)
    )
    if result.first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model not found: {model_tag}",
        )
    await model_router.session.commit()

    # Drop cached copies locally and on every other instance so the new pause
    # state takes effect immediately (otherwise a cached model serves until TTL).
    await model_router.clear_all_caches()
    instances_notified = False
    if cache_invalidator:
        await cache_invalidator.publish("models")
        instances_notified = True

    logger.info(
        "Model pause state changed via admin API",
        extra={"model_tag": model_tag, "paused": body.paused, "reason": reason},
    )
    return ModelPauseResponse(
        model_tag=model_tag,
        paused=body.paused,
        reason=reason,
        instances_notified=instances_notified,
    )


@router.get(
    "/cache/status",
    response_model=CacheStatusResponse,
    summary="Cache status",
    description="Get current cache statistics. Requires admin permission.",
)
async def cache_status(
    api_key: CurrentAPIKey,
    model_router: ModelRouterDep,
    pricing_service: PricingServiceDep,
) -> CacheStatusResponse:
    """Return current cache statistics (sizes, TTLs, live/expired counts)."""
    _require_admin(api_key)

    router_stats = model_router.cache_stats()
    pricing_stats = pricing_service.cache_stats()

    return CacheStatusResponse(
        model_cache=router_stats.get("model_cache", {}),
        routing_cache=router_stats.get("routing_cache", {}),
        pricing_cache=pricing_stats.get("pricing_cache", {}),
    )


@router.get(
    "/models",
    summary="List all models (full registry for the admin console)",
    description=(
        "Every registered model — including deprecated, paused, and operator-"
        "added `local` models — joined with active pricing, the curated model "
        "card (summary + benchmarks) and lineage (generation/tier). Requires "
        "admin permission. This is the data source for the console's model cards."
    ),
)
async def list_all_models(
    api_key: CurrentAPIKey,
    model_router: ModelRouterDep,
) -> dict:
    """Full registry + pricing + curated card, for the admin UI. Unlike the
    served catalog, this shows retired/paused/local models too."""
    _require_admin(api_key)
    session = model_router.session

    models = (await session.execute(select(ModelRegistry))).scalars().all()
    prices = (
        await session.execute(select(ModelPricing).where(ModelPricing.is_active.is_(True)))
    ).scalars().all()

    # Pick one price per model (its own operation, else the first active row).
    price_by_key: dict[tuple[str, str], ModelPricing] = {
        (p.model_tag, p.operation): p for p in prices
    }
    price_first: dict[str, ModelPricing] = {}
    for p in prices:
        price_first.setdefault(p.model_tag, p)

    curated = load_curated()
    cards = curated.get("cards") or {}
    lineage = curated.get("lineage") or {}

    # Serving truth: which configured backend would take each model's calls
    # (null = unserved — the console renders these visibly distinct).
    from mlpal_assistants_service.adapters.factory import get_adapter_factory

    factory = get_adapter_factory()

    def _price(m: ModelRegistry) -> dict | None:
        op = (m.capabilities or {}).get("operation", "chat") if isinstance(m.capabilities, dict) else "chat"
        p = price_by_key.get((m.model_tag, op)) or price_first.get(m.model_tag)
        if p is None:
            return None
        return {
            "input_rate": float(p.input_rate) if p.input_rate is not None else None,
            "output_rate": float(p.output_rate) if p.output_rate is not None else None,
            "rate_unit": p.rate_unit,
        }

    data = [
        {
            "model_tag": m.model_tag,
            "display_name": m.display_name,
            "provider": m.provider,
            "provider_model_id": m.provider_model_id,
            "description": m.description,
            "capabilities": m.capabilities or {},
            "context_length": m.context_length,
            "max_output_tokens": m.max_output_tokens,
            "pricing_tier": m.pricing_tier,
            "priority": m.priority,
            "is_active": m.is_active,
            "is_deprecated": m.is_deprecated,
            "deprecation_message": m.deprecation_message,
            "is_paused": m.is_paused,
            "pause_reason": m.pause_reason,
            "source": m.source,
            "serving_backend": (
                factory.serving_backend_for(m.provider, m.provider_model_id)
                if m.provider != "mlpal"
                else "router"
            ),
            "pricing": _price(m),
            "lineage": lineage.get(m.model_tag),
            "card": cards.get(m.model_tag),
        }
        for m in models
    ]
    return {"data": data, "total": len(data)}


@router.get(
    "/router",
    summary="Router tags — what each mlpal tag currently resolves to",
    description=(
        "The stable routing aliases (`mlpal`, `mlpal-flash`, `mlpal-lite`) and "
        "the concrete model each one currently resolves to, per operation. "
        "Targets upgrade behind the tag — clients pin the tag once and never "
        "change it. Requires admin permission. Data source for the console's "
        "router-tag cards."
    ),
)
async def router_tags(
    request: Request,
    api_key: CurrentAPIKey,
    model_router: ModelRouterDep,
) -> dict:
    """Live resolution table for the mlpal router tags."""
    _require_admin(api_key)
    session = model_router.session

    rows = (
        await session.execute(
            select(MetaModelRouting)
            .where(MetaModelRouting.is_active.is_(True))
            .order_by(
                MetaModelRouting.meta_model_tag,
                MetaModelRouting.operation,
                MetaModelRouting.priority,
            )
        )
    ).scalars().all()

    targets = {r.resolved_model_tag for r in rows}
    registry = {
        m.model_tag: m
        for m in (
            await session.execute(
                select(ModelRegistry).where(ModelRegistry.model_tag.in_(targets))
            )
        ).scalars().all()
    }
    adapters = getattr(request.app.state, "adapters", {})

    def _unserved_reason(m: ModelRegistry | None) -> str | None:
        if m is None:
            return "target not in registry"
        if m.provider not in adapters:
            return "provider not configured"
        if m.is_paused:
            return "model paused"
        if not m.is_active:
            return "model retired"
        return None

    # Full candidate chain per (tag, operation) — resolution semantics mirror
    # the router: the FIRST served candidate is what a request actually gets.
    grouped: dict[tuple[str, str], list[MetaModelRouting]] = {}
    for r in rows:
        grouped.setdefault((r.meta_model_tag, r.operation), []).append(r)

    by_tag: dict[str, list[dict]] = {}
    for (tag, op), cands in sorted(grouped.items()):
        chain = []
        resolves_to = None
        for r in cands:
            m = registry.get(r.resolved_model_tag)
            reason = _unserved_reason(m)
            served = reason is None
            if served and resolves_to is None:
                resolves_to = r.resolved_model_tag
            chain.append(
                {
                    "model_tag": r.resolved_model_tag,
                    "provider": m.provider if m else None,
                    "reason": r.reason,
                    "served": served,
                    "unserved_reason": reason,
                }
            )
        by_tag.setdefault(tag, []).append(
            {
                "operation": op,
                # what a request to this tag gets RIGHT NOW (None = would 503)
                "resolved_model_tag": resolves_to,
                "provider": next(
                    (c["provider"] for c in chain if c["model_tag"] == resolves_to), None
                ),
                "reason": next(
                    (c["reason"] for c in chain if c["model_tag"] == resolves_to), None
                ),
                "served": resolves_to is not None,
                "unserved_reason": None if resolves_to is not None
                else "no candidate served on this deployment",
                "candidates": chain,
            }
        )

    data = [{"tag": tag, "routes": routes} for tag, routes in by_tag.items()]
    return {"data": data, "total": len(data)}


class CaptureToggleRequest(BaseModel):
    enabled: bool


class FeedModeRequest(BaseModel):
    mode: Literal["bundled", "hosted"]
    # The mlpal.ai API key that authenticates feed pulls (free account;
    # a key with zero permissions is recommended — identity only). Stored
    # locally in gateway_meta. Empty string clears it.
    feed_key: str | None = None


@router.get(
    "/config",
    summary="Effective gateway configuration (safe view)",
    description=(
        "The operator-relevant settings this gateway is actually running with, "
        "plus how each can be changed (env var / file / runtime). Never includes "
        "secrets. Requires admin permission."
    ),
)
async def gateway_config(
    request: Request, api_key: CurrentAPIKey, redis_client: RedisDep
) -> dict:
    _require_admin(api_key)
    from mlpal_assistants_service.core.config import get_settings
    from mlpal_assistants_service.services.capture import capture_state

    s = get_settings()
    cap = await capture_state.config(redis_client)
    adapters = getattr(request.app.state, "adapters", {})

    def item(value, changed_via: str, note: str | None = None) -> dict:
        out = {"value": value, "changed_via": changed_via}
        if note:
            out["note"] = note
        return out

    return {
        "environment": item(s.environment, "MLPAL_ENVIRONMENT"),
        "auth_backend": item(
            s.auth_backend, "MLPAL_AUTH_BACKEND", "local = admin API key manages this box"
        ),
        "billing_backend": item(
            s.billing_backend, "MLPAL_BILLING_BACKEND", "local = no wallet callouts"
        ),
        "providers_enabled": item(
            sorted(adapters.keys()),
            "OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY / MLPAL_ENABLE_BEDROCK",
            "adapters activate per key present; restart to apply",
        ),
        "capture": {
            "enabled": cap.enabled,
            "source": cap.source,
            "max_body_kb": cap.max_body_kb,
            "retention_days": cap.retention_days,
            "changed_via": "console toggle (runtime) > MLPAL_CAPTURE_PAYLOADS > config/gateway.yaml",
        },
        "cu_to_usd": item(s.cu_to_usd, "MLPAL_CU_TO_USD", "1 CU = this many USD"),
        "budget_timezone": item(s.budget_timezone, "MLPAL_BUDGET_TIMEZONE"),
        "docs_enabled": item(bool(s.debug), "MLPAL_DEBUG", "Swagger at /docs when true"),
        "config_file": item("config/gateway.yaml", "MLPAL_CONFIG_FILE", "file-defaults layer"),
    }


@router.get(
    "/stats/latency",
    summary="Observed latency by model (p50/p95, ms-per-output-token)",
    description=(
        "Length-normalized latency over recent successful chat traffic — the "
        "same signal that powers the catalog's throughput classes. Requires "
        "admin permission."
    ),
)
async def latency_stats(
    api_key: CurrentAPIKey,
    model_router: ModelRouterDep,
    days: int = Query(default=7, ge=1, le=90),
    min_samples: int = Query(default=1, ge=1, description="Hide models with fewer samples"),
) -> dict:
    _require_admin(api_key)
    from mlpal_assistants_service.repositories.usage_repository import UsageRepository

    stats = await UsageRepository(model_router.session).get_latency_stats_by_model(
        days=days, min_samples=min_samples
    )
    return {"data": stats, "days": days}


@router.get(
    "/budgets",
    summary="Budget burn per key (spend vs cap, current window)",
    description=(
        "For every active key with budget rules: the CU spent in the current "
        "window vs the cap, per rule. Powers the console's budget-burn bars. "
        "Requires admin permission."
    ),
)
async def key_budget_burn(
    api_key: CurrentAPIKey,
    model_router: ModelRouterDep,
) -> dict:
    _require_admin(api_key)
    from zoneinfo import ZoneInfo

    from mlpal_assistants_service.core.config import get_settings
    from mlpal_assistants_service.db.models import APIKey
    from mlpal_assistants_service.repositories.usage_repository import UsageRepository
    from mlpal_assistants_service.services.policy import window_bounds

    settings = get_settings()
    session = model_router.session
    repo = UsageRepository(session)
    now_local = datetime.now(ZoneInfo(settings.budget_timezone))
    cu_to_usd = Decimal(str(settings.cu_to_usd))

    keys = (
        await session.execute(select(APIKey).where(APIKey.is_active.is_(True)))
    ).scalars().all()

    out = []
    for k in keys:
        budgets = k.budgets or []
        if not budgets:
            continue
        rules = []
        for rule in budgets:
            window = rule.get("window", "monthly")
            start, end = window_bounds(window, now_local)
            used_cu = await repo.get_api_key_cu_in_window(k.id, start, end)
            amount = Decimal(str(rule.get("amount", 0)))
            # Normalize the cap to CU (usd caps divide by $/CU).
            cap_cu = amount / cu_to_usd if rule.get("unit") == "usd" else amount
            pct = float(used_cu / cap_cu * 100) if cap_cu > 0 else 0.0
            rules.append(
                {
                    "unit": rule.get("unit"),
                    "amount": float(amount),
                    "window": window,
                    "used_cu": float(used_cu),
                    "cap_cu": float(cap_cu),
                    "pct": round(pct, 1),
                    "window_resets": end.isoformat() if end else None,
                }
            )
        out.append({"api_key_id": k.id, "name": k.name, "rules": rules})

    return {"data": out}


@router.get(
    "/capture",
    summary="Payload-capture status",
    description="Effective capture config and which layer set it (runtime/env/file/default).",
)
async def capture_status(api_key: CurrentAPIKey, redis_client: RedisDep) -> dict:
    _require_admin(api_key)
    from mlpal_assistants_service.services.capture import capture_state

    cfg = await capture_state.config(redis_client)
    return {
        "enabled": cfg.enabled,
        "source": cfg.source,
        "max_body_kb": cfg.max_body_kb,
        "retention_days": cfg.retention_days,
    }


@router.put(
    "/capture",
    summary="Toggle payload capture at runtime",
    description=(
        "Sets the runtime override (highest precedence). Applies to all "
        "instances within ~10s. Capture stores request/response bodies — "
        "opt-in, size-capped, retention-purged."
    ),
)
async def capture_toggle(
    body: CaptureToggleRequest, api_key: CurrentAPIKey, redis_client: RedisDep
) -> dict:
    _require_admin(api_key)
    if redis_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runtime toggle requires Redis; set MLPAL_CAPTURE_PAYLOADS or gateway.yaml instead.",
        )
    from mlpal_assistants_service.services.capture import capture_state

    cfg = await capture_state.set_runtime_override(redis_client, body.enabled)
    logger.info("Payload capture toggled via admin API", extra={"enabled": body.enabled})
    return {"enabled": cfg.enabled, "source": cfg.source}


@router.get(
    "/catalog/feed",
    summary="Catalog-feed subscription status",
)
async def feed_status(
    api_key: CurrentAPIKey, redis_client: RedisDep, model_router: ModelRouterDep
) -> dict:
    _require_admin(api_key)
    from mlpal_assistants_service.services import catalog_feed

    return await catalog_feed.status(redis_client, model_router.session)


@router.put(
    "/catalog/feed",
    summary="Switch catalog-feed mode at runtime",
    description=(
        "bundled = catalog frozen at what this version shipped; hosted = pull "
        "the curated feed on an interval and keep the catalog current. "
        "Switching to hosted runs one sync immediately."
    ),
)
async def feed_toggle(
    body: FeedModeRequest, api_key: CurrentAPIKey, redis_client: RedisDep
) -> dict:
    _require_admin(api_key)
    if redis_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runtime toggle requires Redis; set MLPAL_CATALOG_FEED instead.",
        )
    from mlpal_assistants_service.db.session import async_session_factory
    from mlpal_assistants_service.services import catalog_feed

    await catalog_feed.set_mode(redis_client, body.mode)
    if body.feed_key is not None:
        from mlpal_assistants_service.db.session import async_session_factory as _sf

        async with _sf() as session:
            await catalog_feed.set_meta(
                session, catalog_feed.FEED_KEY_META_KEY, body.feed_key.strip() or None
            )
    logger.info("Catalog feed mode set via admin API", extra={"mode": body.mode})
    result = None
    if body.mode == "hosted":
        result = await catalog_feed.pull_and_reconcile(async_session_factory, redis_client)
    return {"mode": body.mode, "sync": result}


@router.get(
    "/traces/{trace_id}/payload",
    summary="Captured request/response bodies for a trace",
)
async def trace_payload(
    trace_id: str, api_key: CurrentAPIKey, model_router: ModelRouterDep
) -> dict:
    _require_admin(api_key)
    from mlpal_assistants_service.services.capture import fetch_payload

    payload = await fetch_payload(model_router.session, trace_id)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No payload captured for this trace (capture may have been off).",
        )
    return payload


@router.get(
    "/providers",
    summary="Provider key status + live health",
    description=(
        "For each known provider: whether an API key is configured, whether the "
        "adapter is enabled, a LIVE health probe (with latency), the circuit-"
        "breaker-visible state, and how many active models the registry serves "
        "for it. Requires admin permission. Data source for the console's "
        "provider status."
    ),
)
async def provider_status(
    request: Request,
    api_key: CurrentAPIKey,
    model_router: ModelRouterDep,
) -> dict:
    """Live provider status for the operator's supplied keys."""
    _require_admin(api_key)
    import asyncio
    import time as _time

    from mlpal_assistants_service.core.config import get_settings

    settings = get_settings()
    adapters = getattr(request.app.state, "adapters", {})

    # Active model count per provider (from the registry).
    counts: dict[str, int] = {}
    rows = (
        await model_router.session.execute(
            select(ModelRegistry.provider, func.count())
            .where(ModelRegistry.is_active.is_(True))
            .group_by(ModelRegistry.provider)
        )
    ).all()
    for provider, n in rows:
        counts[provider] = n

    # Family-aware: a box with only a cloud backend (Azure/Vertex/Bedrock-
    # Claude) counts as configured for that family even without the first-
    # party key. The factory owns that logic.
    from mlpal_assistants_service.adapters.factory import get_adapter_factory

    factory = get_adapter_factory()
    configured = {
        name: factory.is_enabled(name)
        for name in ("openai", "anthropic", "google", "bedrock")
    }

    async def probe(name: str, adapter) -> dict:
        t0 = _time.perf_counter()
        try:
            healthy = await asyncio.wait_for(adapter.health_check(), timeout=3.0)
            return {"healthy": bool(healthy), "latency_ms": int((_time.perf_counter() - t0) * 1000), "error": None}
        except TimeoutError:
            return {"healthy": False, "latency_ms": 3000, "error": "health check timed out"}
        except Exception as e:  # noqa: BLE001 — surface the reason to the operator
            return {"healthy": False, "latency_ms": int((_time.perf_counter() - t0) * 1000), "error": str(e)[:200]}

    probes = dict(
        zip(
            adapters.keys(),
            await asyncio.gather(*[probe(n, a) for n, a in adapters.items()]),
            strict=True,
        )
    )

    data = []
    for name in ("openai", "anthropic", "google", "bedrock"):
        active = name in adapters
        entry: dict = {
            "provider": name,
            "configured": configured.get(name, False),
            "enabled": active,
            "models_active": counts.get(name, 0),
            # Multi-cloud serving: the primary backend actually serving this
            # family, and the full priority order (MLPAL_<FAMILY>_BACKENDS).
            "serving_backend": adapters[name].backend_name if name in adapters else None,
            "backend_priority": factory.backend_priority(name),
        }
        if active and name in probes:
            entry["health"] = probes[name]
        else:
            entry["health"] = None  # not probed — no key / disabled
        data.append(entry)

    return {"data": data}


@router.get(
    "/traces",
    summary="List request traces (per-request usage records)",
    description=(
        "Paginated per-request records from usage_logs — trace_id, model, "
        "provider, operation, tokens, compute units, "
        "latency, status, and metadata. Filterable by status, model, operation, "
        "api key, and time window. Requires admin permission. This is the data "
        "source for the console's Traces view."
    ),
)
async def list_traces(
    api_key: CurrentAPIKey,
    model_router: ModelRouterDep,
    status_filter: str | None = Query(default=None, alias="status", description="success | error"),
    model_tag: str | None = Query(default=None, description="Filter by resolved model tag"),
    operation: str | None = Query(default=None, description="chat | embedding | image_generation | tts | transcription"),
    api: str | None = Query(default=None, description="Surface tag: v1_messages | v2_messages"),
    api_key_id: int | None = Query(default=None, description="Filter by API key id"),
    trace_id: str | None = Query(default=None, description="Exact trace id lookup"),
    hours: int = Query(default=24, ge=1, le=24 * 90, description="Look-back window in hours"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Recent request traces, newest first (global — operator view)."""
    _require_admin(api_key)
    out = await query_traces(
        model_router.session,
        user_id=None,  # admin surface: global
        status=status_filter,
        model_tag=model_tag,
        operation=operation,
        api=api,
        api_key_id=api_key_id,
        trace_id=trace_id,
        since=datetime.now(UTC) - timedelta(hours=hours),
        limit=limit,
        offset=offset,
    )
    out["window_hours"] = hours
    return out
