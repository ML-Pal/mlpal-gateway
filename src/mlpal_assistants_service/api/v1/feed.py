"""Public catalog feed endpoint.

Serves this deployment's bundled catalog as a feed document any other gateway
can subscribe to (``MLPAL_CATALOG_FEED=hosted``). Deliberately UNAUTHENTICATED:
the catalog is public data (it's in the open-source repo), and anonymous pulls
are what let self-hosted boxes stay current with zero signup friction.

Subscribers send two optional headers — ``X-MLPal-Instance`` (random UUID) and
``X-MLPal-Version`` — which are upserted into ``feed_installs`` so the operator
can count active installs. The upsert is fire-and-forget and never blocks or
fails the response.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Header, Response

from mlpal_assistants_service.db.session import async_session_factory
from mlpal_assistants_service.services.catalog_feed import load_bundled_feed, record_install

logger = logging.getLogger(__name__)

router = APIRouter()

_TASKS: set[asyncio.Task] = set()

# The bundled feed is immutable for the process lifetime — compute once.
_FEED_CACHE: dict | None = None


def _feed() -> dict:
    global _FEED_CACHE
    if _FEED_CACHE is None:
        _FEED_CACHE = load_bundled_feed()
    return _FEED_CACHE


async def _track(instance_id: str, version: str | None, email: str | None) -> None:
    try:
        async with async_session_factory() as session:
            await record_install(session, instance_id, version, email)
    except Exception:  # noqa: BLE001 — tracking must never matter to the caller
        logger.debug("feed install upsert failed", exc_info=True)


@router.get(
    "/catalog/feed",
    summary="Catalog feed (public)",
    response_model=None,
    description=(
        "The curated model catalog (registry, pricing, routing) as a feed "
        "document. Self-hosted gateways subscribe with MLPAL_CATALOG_FEED=hosted."
    ),
)
async def catalog_feed(
    response: Response,
    if_none_match: str | None = Header(default=None),
    x_mlpal_instance: str | None = Header(default=None),
    x_mlpal_version: str | None = Header(default=None),
    x_mlpal_contact: str | None = Header(default=None),
) -> dict | Response:
    doc = _feed()
    etag = f'"{doc["feed_version"]}"'
    if x_mlpal_instance and len(x_mlpal_instance) <= 64:
        email = (x_mlpal_contact or "").strip()[:320] or None
        if email and "@" not in email:
            email = None
        task = asyncio.get_running_loop().create_task(
            _track(x_mlpal_instance, (x_mlpal_version or "")[:64] or None, email)
        )
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return doc
