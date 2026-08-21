"""Connections runtime: tenant serving sources (BYOK keys + BYOM endpoints).

Hot-path contract (design doc planning/designs/connections-byom.md):
- Users with no connections pay ONE in-process dict probe (negative results
  are cached with the same TTL) — no I/O is added to their requests.
- Connection users pay overlay-dict + LRU-pool hits. The secret is revealed
  only on pool miss (first use / rotation / eviction), never per request.
- byok serve-time precedence per family: tenant azure → tenant first_party →
  deployment credentials. A tenant's bad key never affects other tenants
  (tenant adapters are outside the shared circuit breakers) and never hard-
  fails resolution — errors surface per-request with attribution.
- byom: `user/…` tags resolve through a per-user model overlay, never the
  shared model caches — a tenant model is invisible to every other tenant.

Invalidation: writes bump the row's updated_at; overlay caches are TTL'd
(60s) and explicitly dropped via the cache-invalidation pub/sub target
"connections" (published by the API on every change), so a rotated key takes
effect within a second on every worker.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from mlpal_assistants_service.core.config import get_settings
from mlpal_assistants_service.db.models.connections import TenantConnection, TenantModel

logger = logging.getLogger(__name__)

OVERLAY_TTL_SECONDS = 60.0

# Reserved namespace for tenant models. Catalog rows can never carry it
# (catalog_sync rejects them), so collision is structurally impossible.
USER_TAG_PREFIX = "user/"
USER_TAG_RE = re.compile(r"^user/[a-z0-9][a-z0-9._-]{0,62}$")

# byok family/backend targets servable with tenant credentials in v1.
SUPPORTED: dict[tuple[str, str], bool] = {
    ("anthropic", "first_party"): True,
    ("openai", "first_party"): True,
    ("openai", "azure"): True,
    ("google", "first_party"): True,
}

# byom wire dialects the gateway can speak in v1.
BYOM_DIALECTS = ("openai",)


@dataclass(frozen=True)
class Conn:
    id: int
    user_id: int
    kind: str  # "byok" | "byom"
    family: str  # byok: provider family; byom: wire dialect
    backend: str  # byok: first_party|azure; byom: "custom"
    secret_ref: str
    driver: str
    status: str
    fallback: str  # "mlpal" (auto-switch, billed) | "none" (hard-stop)
    config: dict | None
    version: str  # updated_at iso — cache/pool key component


@dataclass(frozen=True)
class TenantModelRef:
    id: int
    model_tag: str
    provider_model_id: str
    operation: str
    context_length: int
    max_output_tokens: int | None
    input_price_per_m: Decimal
    output_price_per_m: Decimal
    capabilities: dict | None
    conn: Conn


class ConnectionBlocked(Exception):
    """A byok credential is invalid AND the user opted out of MLPal
    fallback — the request must fail with attribution, not silently bill."""

    def __init__(self, family: str) -> None:
        self.family = family
        super().__init__(
            f"Your {family} API key is invalid and automatic fallback to "
            "MLPal's keys is disabled for it (connection_rejected). Update "
            "the key in Settings → Connections to resume serving."
        )


def _conn_from_row(r: TenantConnection) -> Conn:
    return Conn(
        id=r.id,
        user_id=r.user_id,
        kind=r.kind,
        family=r.family,
        backend=r.backend,
        secret_ref=r.secret_ref,
        driver=r.driver,
        status=r.status,
        fallback=r.fallback or "mlpal",
        config=r.config,
        version=str(r.updated_at),
    )


# ── byok overlay: user_id -> (expires_at, {family: [conns by precedence]}) ──
_overlay: dict[int, tuple[float, dict[str, list[Conn]]]] = {}

# ── byom overlay: user_id -> (expires_at, {model_tag: TenantModelRef}) ──────
_model_overlay: dict[int, tuple[float, dict[str, TenantModelRef]]] = {}


def _precedence(conns: list[Conn]) -> list[Conn]:
    # azure (their infra/credits) outranks their first_party.
    return sorted(conns, key=lambda c: 0 if c.backend == "azure" else 1)


async def get_overlay(user_id: int, session: Any) -> dict[str, list[Conn]]:
    """byok credential map for a user. Cached; the empty dict for users with
    no connections is cached too, so the common case never touches the DB
    twice a minute per worker."""
    hit = _overlay.get(user_id)
    now = time.monotonic()
    if hit is not None and hit[0] > now:
        return hit[1]
    rows = (
        (
            await session.execute(
                select(TenantConnection).where(
                    TenantConnection.user_id == user_id,
                    TenantConnection.kind == "byok",
                )
            )
        )
        .scalars()
        .all()
    )
    by_family: dict[str, list[Conn]] = {}
    for r in rows:
        if (r.family, r.backend) not in SUPPORTED:
            continue
        # Invalid creds stay in the overlay (marked) — serving skips them,
        # but fallback="none" must be able to BLOCK instead of silently
        # switching the user onto billed MLPal keys.
        by_family.setdefault(r.family, []).append(_conn_from_row(r))
    overlay = {fam: _precedence(conns) for fam, conns in by_family.items()}
    _overlay[user_id] = (now + OVERLAY_TTL_SECONDS, overlay)
    return overlay


async def get_model_overlay(user_id: int, session: Any) -> dict[str, TenantModelRef]:
    """byom model map for a user: active `user/…` tags → refs (each carrying
    its connection). Cached with the same TTL/invalidation as the byok
    overlay; per-user keys only — never the shared model caches."""
    hit = _model_overlay.get(user_id)
    now = time.monotonic()
    if hit is not None and hit[0] > now:
        return hit[1]
    rows = (
        await session.execute(
            select(TenantModel, TenantConnection)
            .join(TenantConnection, TenantModel.connection_id == TenantConnection.id)
            .where(TenantModel.user_id == user_id, TenantModel.is_active.is_(True))
        )
    ).all()
    models: dict[str, TenantModelRef] = {}
    for m, c in rows:
        models[m.model_tag] = TenantModelRef(
            id=m.id,
            model_tag=m.model_tag,
            provider_model_id=m.provider_model_id,
            operation=m.operation,
            context_length=m.context_length,
            max_output_tokens=m.max_output_tokens,
            input_price_per_m=m.input_price_per_m,
            output_price_per_m=m.output_price_per_m,
            capabilities=m.capabilities,
            conn=_conn_from_row(c),
        )
    _model_overlay[user_id] = (now + OVERLAY_TTL_SECONDS, models)
    return models


def invalidate_overlay(user_id: int | None = None) -> None:
    if user_id is None:
        _overlay.clear()
        _model_overlay.clear()
    else:
        _overlay.pop(user_id, None)
        _model_overlay.pop(user_id, None)


# ── tenant adapter pool (bounded LRU) ────────────────────────────────────────

_pool: OrderedDict[tuple, Any] = OrderedDict()
_pool_lock = asyncio.Lock()


async def _build_adapter(conn: Conn, api_key: str) -> Any:
    from mlpal_assistants_service.adapters.anthropic import AnthropicAdapter
    from mlpal_assistants_service.adapters.google import GoogleAdapter
    from mlpal_assistants_service.adapters.openai import OpenAIAdapter

    if conn.kind == "byom":
        if conn.family not in BYOM_DIALECTS:
            raise ValueError(f"unsupported byom dialect {conn.family}")
        from mlpal_assistants_service.seams.egress_guard import validate_endpoint

        endpoint = (conn.config or {}).get("endpoint", "").rstrip("/")
        await validate_endpoint(endpoint)
        adapter = OpenAIAdapter(api_key=api_key or "none", base_url=endpoint + "/")
        adapter.backend_name = "custom"  # instance-level: provenance in traces
        # Most OpenAI-compatible servers (vLLM, Ollama, TGI, Together) speak
        # /v1/chat/completions but NOT /v1/responses — byom always uses the
        # standard wire.
        adapter.wire = "chat_completions"
        # Their endpoint is authoritative for params too — accept any
        # non-reserved model_kwargs and let it validate (loudly, but theirs).
        adapter.accept_all_kwargs = True
        # Resolution already mapped user/ tag → wire id; pass through.
        adapter.serves = lambda mid: True  # type: ignore[method-assign]
        adapter.backend_model_id = lambda mid: mid  # type: ignore[method-assign]
        return adapter
    if conn.family == "anthropic":
        return AnthropicAdapter(api_key=api_key)
    if conn.family == "google":
        return GoogleAdapter(api_key=api_key)
    if conn.family == "openai" and conn.backend == "first_party":
        return OpenAIAdapter(api_key=api_key)
    if conn.family == "openai" and conn.backend == "azure":
        endpoint = (conn.config or {}).get("endpoint", "").rstrip("/")
        adapter = OpenAIAdapter(api_key=api_key, base_url=endpoint + "/openai/v1/")
        adapter.backend_name = "azure"  # instance-level: provenance in traces
        deployments = (conn.config or {}).get("deployments") or {}
        if deployments:
            adapter.serves = lambda mid: mid in deployments  # type: ignore[method-assign]
            adapter.backend_model_id = lambda mid: deployments.get(mid, mid)  # type: ignore[method-assign]
        return adapter
    raise ValueError(f"unsupported connection target {conn.family}/{conn.backend}")


async def get_tenant_adapter(conn: Conn) -> Any:
    """Adapter for a tenant connection — pooled, secret revealed on miss."""
    key = (conn.id, conn.version)
    async with _pool_lock:
        if key in _pool:
            _pool.move_to_end(key)
            return _pool[key]
    from mlpal_assistants_service.seams.custody import build_custody

    api_key = await build_custody().reveal(conn.user_id, conn.secret_ref)
    adapter = await _build_adapter(conn, api_key)
    async with _pool_lock:
        _pool[key] = adapter
        _pool.move_to_end(key)
        maxsize = get_settings().connections_pool_size
        while len(_pool) > maxsize:
            _, evicted = _pool.popitem(last=False)
            _close_soon(evicted)
    return adapter


def _close_soon(adapter: Any) -> None:
    client = getattr(adapter, "_client", None)
    close = getattr(client, "close", None) or getattr(client, "aclose", None)
    if close is None:
        return
    try:
        result = close()
        if asyncio.iscoroutine(result):
            task = asyncio.get_running_loop().create_task(result)
            task.add_done_callback(lambda t: t.exception())
    except Exception:  # noqa: BLE001 — eviction cleanup is best-effort
        pass


def clear_pool() -> None:
    """Testing hook."""
    _pool.clear()
    _overlay.clear()
    _model_overlay.clear()


async def resolve_tenant_adapter(
    user_id: int, session: Any, family: str, provider_model_id: str
) -> tuple[Any, str, Conn] | None:
    """byok overlay entry point for serving paths. Returns
    (adapter, wire_model_id, conn) when a tenant credential should serve
    this catalog model, else None (→ deployment resolution, unchanged path).

    Never raises on custody/build failure — a broken tenant credential must
    degrade to deployment keys, not break the request."""
    if not get_settings().connections_enabled:
        return None
    try:
        overlay = await get_overlay(user_id, session)
    except Exception:  # noqa: BLE001 — overlay read must not break serving
        logger.warning(
            "connections: overlay read failed for user %s", user_id, exc_info=True
        )
        return None
    conns = overlay.get(family)
    if not conns:
        return None
    for conn in conns:
        if conn.status == "invalid":
            continue
        try:
            adapter = await get_tenant_adapter(conn)
        except Exception:  # noqa: BLE001 — fall through to next conn / deployment
            logger.warning(
                "connections: adapter build failed for user %s %s/%s",
                user_id,
                conn.family,
                conn.backend,
                exc_info=True,
            )
            continue
        if adapter.serves(provider_model_id):
            return adapter, adapter.backend_model_id(provider_model_id), conn
    _raise_if_fallback_blocked(family, conns)
    return None


async def resolve_tenant_model(
    user_id: int, session: Any, model_tag: str
) -> tuple[Any, str, TenantModelRef] | None:
    """byom entry point: resolve a `user/…` tag to (adapter, wire_model_id,
    model_ref). None when the tag isn't registered / inactive / feature off —
    callers surface that as model-not-found, exactly like an unknown catalog
    tag. Build failures also return None (a broken endpoint must read as
    "model unavailable", with the error attributed on the connection row)."""
    if not get_settings().connections_enabled:
        return None
    if not model_tag.startswith(USER_TAG_PREFIX):
        return None
    try:
        models = await get_model_overlay(user_id, session)
    except Exception:  # noqa: BLE001 — overlay read must not break serving
        logger.warning(
            "connections: model overlay read failed for user %s", user_id, exc_info=True
        )
        return None
    ref = models.get(model_tag)
    if ref is None or ref.conn.status == "invalid":
        return None
    try:
        adapter = await get_tenant_adapter(ref.conn)
    except Exception:  # noqa: BLE001
        logger.warning(
            "connections: byom adapter build failed for user %s conn %s",
            user_id,
            ref.conn.id,
            exc_info=True,
        )
        return None
    return adapter, ref.provider_model_id, ref


def byom_usd_estimate(ref: TenantModelRef, tokens_in: int, tokens_out: int) -> Decimal:
    """Cost estimate at the user's declared prices (their visibility only —
    never billed)."""
    return (
        Decimal(tokens_in) * ref.input_price_per_m
        + Decimal(tokens_out) * ref.output_price_per_m
    ) / Decimal(1_000_000)


def _raise_if_fallback_blocked(family: str, conns: list[Conn]) -> None:
    """No tenant credential could serve. If any of this family's byok conns
    is invalid with fallback="none", the user chose hard-stop over billed
    fallback — honor it."""
    if any(c.status == "invalid" and c.fallback == "none" for c in conns):
        raise ConnectionBlocked(family)


async def mark_invalid(session: Any, conn_id: int, error: str) -> None:
    """Serve-time attribution: provider rejected the tenant key — flip the
    row so the console shows why and serving falls back to deployment keys."""
    from sqlalchemy import update

    await session.execute(
        update(TenantConnection)
        .where(TenantConnection.id == conn_id)
        .values(status="invalid", error=error[:300])
    )
    await session.commit()
    invalidate_overlay()


async def plan_tenant_serving(
    user_id: int, session: Any, model: Any
) -> tuple[str, Any, str, Conn] | None:
    """Serving plan for /v1/messages catalog models: ("native", backend,
    wire_id, conn) for BYO-Anthropic (byte-faithful passthrough preserved),
    ("adapter", adapter, wire_id, conn) otherwise. None → deployment path,
    unchanged."""
    family = model.provider
    if family == "anthropic":
        conn_backend = await _resolve_tenant_native(user_id, session)
        if conn_backend is not None:
            backend, conn = conn_backend
            return ("native", backend, model.provider_model_id, conn)
        return None
    resolved = await resolve_tenant_adapter(
        user_id, session, family, model.provider_model_id
    )
    if resolved is None:
        return None
    adapter, wire_id, conn = resolved
    return ("adapter", adapter, wire_id, conn)


async def _resolve_tenant_native(
    user_id: int, session: Any
) -> tuple[Any, Conn] | None:
    """Pooled per-tenant native Anthropic backend (their key, our base_url)."""
    if not get_settings().connections_enabled:
        return None
    try:
        overlay = await get_overlay(user_id, session)
    except Exception:  # noqa: BLE001
        logger.warning(
            "connections: overlay read failed for user %s", user_id, exc_info=True
        )
        return None
    conns = overlay.get("anthropic")
    if not conns:
        return None
    servable = [c for c in conns if c.status != "invalid"]
    if not servable:
        _raise_if_fallback_blocked("anthropic", conns)
        return None
    conn = servable[0]  # anthropic v1 = first_party only
    key = ("native", conn.id, conn.version)
    async with _pool_lock:
        if key in _pool:
            _pool.move_to_end(key)
            return _pool[key], conn
    try:
        from mlpal_assistants_service.seams.custody import build_custody
        from mlpal_assistants_service.services.messages_v2.anthropic_backend import (
            AnthropicFirstPartyBackend,
        )

        api_key = await build_custody().reveal(conn.user_id, conn.secret_ref)
        backend = AnthropicFirstPartyBackend(get_settings())
        backend._api_key = api_key  # tenant key; url/version stay deployment defaults
    except Exception:  # noqa: BLE001 — degrade to deployment keys
        logger.warning(
            "connections: native backend build failed for user %s", user_id, exc_info=True
        )
        return None
    async with _pool_lock:
        _pool[key] = backend
        _pool.move_to_end(key)
    return backend, conn
