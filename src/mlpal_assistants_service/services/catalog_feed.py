"""Hosted catalog feed: serving, subscribing, and install identity.

Every gateway ships a bundled catalog (``catalog/*.json``) and can serve it at
``GET /v1/catalog/feed``. A deployment may also SUBSCRIBE to another gateway's
feed (normally the managed one at models.mlpal.ai): a background task pulls the
feed on an interval and applies it through the idempotent
``catalog_sync.reconcile`` — so model retirements and additions are absorbed
without upgrading the box.

Modes (runtime Redis override > env, mirroring the capture toggle):
- ``bundled`` (default): catalog frozen at what this version shipped.
- ``hosted``: pull from ``catalog_feed_url`` every ``catalog_feed_interval_hours``.

Feed pulls are AUTHENTICATED with an mlpal.ai API key (free account; identity
only — no permissions needed, no charges possible from feed pulls). A pull
sends the key plus a per-install UUID and the gateway version, linking the
install to the subscriber's account. Bundled mode sends nothing, ever.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from importlib import resources
from typing import Any

import httpx

from mlpal_assistants_service.core.config import get_settings

logger = logging.getLogger(__name__)

MODE_KEY = "feed:mode"          # runtime override: "bundled" | "hosted"
ETAG_KEY = "feed:etag"
LAST_SYNC_KEY = "feed:last_sync"  # JSON blob for the console
INSTANCE_META_KEY = "instance_id"
FEED_KEY_META_KEY = "feed_key"  # the mlpal.ai key that authenticates pulls

_BACKGROUND: set[asyncio.Task] = set()


# -- bundled feed ------------------------------------------------------------

def load_bundled_feed() -> dict[str, Any]:
    """The catalog this build ships, as a feed document with a content hash.

    Pricing is normalized to markup 1.00 before serving: the markup multiplier
    is deployment-specific business config (the managed deployment bundles its
    own values), never catalog data — the same scrub build-oss.sh applies to
    the public repo. Subscribers always receive pass-through pricing.
    """
    pkg = resources.files("mlpal_assistants_service") / "catalog"
    doc: dict[str, Any] = {}
    for name in ("registry", "pricing", "routing"):
        doc[name] = json.loads((pkg / f"{name}.json").read_text())
    for row in doc["pricing"]:
        if "markup_multiplier" in row:
            old = row["markup_multiplier"]
            row["markup_multiplier"] = "1.00" if isinstance(old, str) else 1.00
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    doc["feed_version"] = hashlib.sha256(canonical).hexdigest()[:12]
    doc["generated_at"] = datetime.now(UTC).isoformat()
    doc["latest_gateway_version"] = gateway_version()
    return doc


def gateway_version() -> str:
    from importlib.metadata import version

    for dist in ("mlpal-gateway", "mlpal-assistants-service"):
        try:
            return version(dist)
        except Exception:  # noqa: BLE001
            continue
    # Container images run from source without installing the project — read
    # the version straight from the bundled pyproject.
    try:
        import pathlib
        import tomllib

        for parent in pathlib.Path(__file__).resolve().parents:
            pp = parent / "pyproject.toml"
            if pp.exists():
                return tomllib.loads(pp.read_text())["project"]["version"]
    except Exception:  # noqa: BLE001
        pass
    return "0.0.0-dev"


# -- mode + status (Redis runtime override > env default) --------------------

async def effective_mode(redis: Any) -> tuple[str, str]:
    """(mode, source). Runtime override wins; else the env/settings default."""
    if redis is not None:
        try:
            override = await redis.get(MODE_KEY)
            if override in ("bundled", "hosted"):
                return override, "runtime"
        except Exception:  # noqa: BLE001
            pass
    return get_settings().catalog_feed_mode, "env"


async def set_mode(redis: Any, mode: str) -> None:
    await redis.set(MODE_KEY, mode)


async def status(redis: Any, session: Any) -> dict[str, Any]:
    mode, source = await effective_mode(redis)
    last_sync = None
    if redis is not None:
        try:
            raw = await redis.get(LAST_SYNC_KEY)
            last_sync = json.loads(raw) if raw else None
        except Exception:  # noqa: BLE001
            pass
    return {
        "mode": mode,
        "source": source,
        "feed_url": get_settings().catalog_feed_url,
        "bundled_version": load_bundled_feed()["feed_version"],
        "gateway_version": gateway_version(),
        "last_sync": last_sync,
        "instance_id": await get_instance_id(session) if session is not None else None,
        "feed_key_set": bool(await get_meta(session, FEED_KEY_META_KEY)) if session is not None else False,
    }


# -- install identity --------------------------------------------------------

async def get_instance_id(session: Any) -> str:
    """Stable anonymous UUID for this deployment, created on first use."""
    from sqlalchemy import select

    from mlpal_assistants_service.db.models.feed import GatewayMeta

    row = (
        await session.execute(select(GatewayMeta).where(GatewayMeta.key == INSTANCE_META_KEY))
    ).scalar_one_or_none()
    if row is not None:
        return row.value
    value = str(uuid.uuid4())
    session.add(GatewayMeta(key=INSTANCE_META_KEY, value=value))
    try:
        await session.commit()
    except Exception:  # noqa: BLE001 — raced by a sibling worker: theirs wins
        await session.rollback()
        row = (
            await session.execute(select(GatewayMeta).where(GatewayMeta.key == INSTANCE_META_KEY))
        ).scalar_one_or_none()
        return row.value if row else value
    return value


async def get_meta(session: Any, key: str) -> str | None:
    from sqlalchemy import select

    from mlpal_assistants_service.db.models.feed import GatewayMeta

    row = (
        await session.execute(select(GatewayMeta).where(GatewayMeta.key == key))
    ).scalar_one_or_none()
    return row.value if row else None


async def set_meta(session: Any, key: str, value: str | None) -> None:
    from sqlalchemy import select

    from mlpal_assistants_service.db.models.feed import GatewayMeta

    row = (
        await session.execute(select(GatewayMeta).where(GatewayMeta.key == key))
    ).scalar_one_or_none()
    if value:
        if row is None:
            session.add(GatewayMeta(key=key, value=value))
        else:
            row.value = value
    elif row is not None:
        await session.delete(row)
    await session.commit()


async def record_install(
    session: Any,
    instance_id: str,
    version: str | None,
    user_id: int | None = None,
    api_key_id: int | None = None,
) -> None:
    """Upsert a feed_installs row for a pulling instance (feed-server side)."""
    from sqlalchemy import select

    from mlpal_assistants_service.db.models.feed import FeedInstall

    row = (
        await session.execute(select(FeedInstall).where(FeedInstall.instance_id == instance_id))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None:
        session.add(
            FeedInstall(
                instance_id=instance_id, first_seen=now, last_seen=now,
                gateway_version=version, pull_count=1,
                user_id=user_id, api_key_id=api_key_id,
            )
        )
    else:
        row.last_seen = now
        row.gateway_version = version or row.gateway_version
        row.pull_count += 1
        if user_id is not None:
            row.user_id = user_id
            row.api_key_id = api_key_id
    await session.commit()


# -- subscriber --------------------------------------------------------------

async def pull_and_reconcile(session_factory: Any, redis: Any) -> dict[str, Any]:
    """One feed pull: fetch (ETag-aware), reconcile if changed, record status.
    Returns the status blob written to Redis. Never raises."""
    settings = get_settings()
    out: dict[str, Any] = {"at": datetime.now(UTC).isoformat(), "url": settings.catalog_feed_url}
    try:
        headers = {}
        async with session_factory() as session:
            headers["X-MLPal-Instance"] = await get_instance_id(session)
            feed_key = await get_meta(session, FEED_KEY_META_KEY)
        headers["X-MLPal-Version"] = gateway_version()
        if not feed_key:
            out.update(result="error", error="no feed key — subscribe with a free mlpal.ai API key")
            if redis is not None:
                try:
                    await redis.set(LAST_SYNC_KEY, json.dumps(out))
                except Exception:  # noqa: BLE001
                    pass
            return out
        headers["Authorization"] = f"Bearer {feed_key}"
        if redis is not None:
            etag = await redis.get(ETAG_KEY)
            if etag:
                headers["If-None-Match"] = etag
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(settings.catalog_feed_url, headers=headers)
        if resp.status_code == 304:
            out.update(result="unchanged")
        elif resp.status_code == 200:
            doc = resp.json()
            from mlpal_assistants_service.services.catalog_sync import reconcile

            routing_doc = doc.get("routing")
            # routing.json is a wrapper doc ({_note, updated, routes}); the
            # reconcile wants the routes list (same normalization as
            # scripts/reconcile_catalog.py).
            routing = routing_doc.get("routes") if isinstance(routing_doc, dict) else routing_doc
            async with session_factory() as session:
                summary = await reconcile(
                    session, doc["registry"], doc["pricing"], routing,
                    retire_message="Retired from the hosted MLPal catalog feed",
                )
                await session.commit()
            out.update(
                result="applied",
                feed_version=doc.get("feed_version"),
                latest_gateway_version=doc.get("latest_gateway_version"),
                inserted=summary.inserted, updated=summary.updated, retired=summary.retired,
            )
            if redis is not None and resp.headers.get("etag"):
                await redis.set(ETAG_KEY, resp.headers["etag"])
            logger.info("catalog feed applied", extra=out)
        else:
            out.update(result="error", status=resp.status_code)
            logger.warning("catalog feed pull failed: HTTP %s", resp.status_code)
    except Exception as e:  # noqa: BLE001 — subscription must never hurt serving
        out.update(result="error", error=str(e)[:200])
        logger.warning("catalog feed pull failed: %s", e)
    if redis is not None:
        try:
            await redis.set(LAST_SYNC_KEY, json.dumps(out))
        except Exception:  # noqa: BLE001
            pass
    return out


def start_subscriber(session_factory: Any, redis: Any) -> None:
    """Start the background loop (lifespan). Checks mode every cycle so the runtime
    toggle takes effect without a restart; bundled mode pulls nothing."""

    async def _loop() -> None:
        settings = get_settings()
        await asyncio.sleep(60)  # never in the boot path
        while True:
            mode, _ = await effective_mode(redis)
            if mode == "hosted":
                await pull_and_reconcile(session_factory, redis)
            await asyncio.sleep(settings.catalog_feed_interval_hours * 3600)

    task = asyncio.get_running_loop().create_task(_loop())
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
