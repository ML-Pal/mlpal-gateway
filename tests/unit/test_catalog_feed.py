"""Hosted catalog feed: bundled document, install identity/upsert, mode
resolution, and the subscriber's pull→reconcile path (HTTP mocked)."""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mlpal_assistants_service.db.models import Base
from mlpal_assistants_service.db.models.feed import FeedInstall, GatewayMeta
from mlpal_assistants_service.services import catalog_feed


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={"schema_translate_map": {"assistants": None, "users": None}},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c, tables=[GatewayMeta.__table__, FeedInstall.__table__]
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


def test_bundled_feed_shape_and_stable_version():
    doc = catalog_feed.load_bundled_feed()
    assert {"registry", "pricing", "routing", "feed_version"} <= set(doc)
    assert len(doc["registry"]) > 50  # the curated catalog, not a stub
    assert doc["feed_version"] == catalog_feed.load_bundled_feed()["feed_version"]


@pytest.mark.asyncio
async def test_instance_id_stable(session_factory):
    async with session_factory() as s:
        a = await catalog_feed.get_instance_id(s)
    async with session_factory() as s:
        b = await catalog_feed.get_instance_id(s)
    assert a == b and len(a) == 36


@pytest.mark.asyncio
async def test_record_install_upserts(session_factory):
    async with session_factory() as s:
        await catalog_feed.record_install(s, "inst-1", "0.2.3")
        await catalog_feed.record_install(s, "inst-1", "0.3.0")
        await catalog_feed.record_install(s, "inst-2", None)
    async with session_factory() as s:
        rows = {r.instance_id: r for r in (await s.execute(select(FeedInstall))).scalars()}
    assert rows["inst-1"].pull_count == 2
    assert rows["inst-1"].gateway_version == "0.3.0"
    assert rows["inst-2"].pull_count == 1


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, k):
        return self.store.get(k)

    async def set(self, k, v):
        self.store[k] = v


@pytest.mark.asyncio
async def test_effective_mode_precedence():
    redis = _FakeRedis()
    mode, source = await catalog_feed.effective_mode(redis)
    assert (mode, source) == ("bundled", "env")  # settings default
    await catalog_feed.set_mode(redis, "hosted")
    mode, source = await catalog_feed.effective_mode(redis)
    assert (mode, source) == ("hosted", "runtime")
    # garbage in Redis falls back to env
    redis.store[catalog_feed.MODE_KEY] = "banana"
    mode, source = await catalog_feed.effective_mode(redis)
    assert source == "env"


@pytest.mark.asyncio
async def test_pull_applies_feed(session_factory, monkeypatch):
    """A 200 feed response flows through catalog_sync.reconcile; ETag stored."""
    feed_doc = {
        "feed_version": "abc123",
        "latest_gateway_version": "9.9.9",
        "registry": [], "pricing": [],
        # the real feed wraps routes in a doc — the client must unwrap it
        "routing": {"_note": "x", "updated": "2026-08-12", "routes": [{"meta_model_tag": "mlpal"}]},
    }

    class _Resp:
        status_code = 200
        headers = {"etag": '"abc123"'}

        def json(self):
            return feed_doc

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url, headers=None):
            _Client.sent_headers = headers
            return _Resp()

    monkeypatch.setattr(catalog_feed.httpx, "AsyncClient", _Client)

    applied = {}

    async def fake_reconcile(session, registry, pricing, routing=None, *, retire_message=None):
        applied.update(registry=registry, pricing=pricing, routing=routing)

        class S:
            inserted = updated = retired = 0
        return S()

    import mlpal_assistants_service.services.catalog_sync as cs
    monkeypatch.setattr(cs, "reconcile", fake_reconcile)

    redis = _FakeRedis()
    out = await catalog_feed.pull_and_reconcile(session_factory, redis)
    assert out["result"] == "applied"
    assert applied == {"registry": [], "pricing": [], "routing": [{"meta_model_tag": "mlpal"}]}
    assert redis.store[catalog_feed.ETAG_KEY] == '"abc123"'
    # identity + version headers went out (the documented telemetry, nothing else)
    assert set(_Client.sent_headers) == {"X-MLPal-Instance", "X-MLPal-Version"}
    # status blob is written for the console
    assert json.loads(redis.store[catalog_feed.LAST_SYNC_KEY])["result"] == "applied"


@pytest.mark.asyncio
async def test_pull_304_is_unchanged(session_factory, monkeypatch):
    class _Resp:
        status_code = 304
        headers = {}

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url, headers=None):
            return _Resp()

    monkeypatch.setattr(catalog_feed.httpx, "AsyncClient", _Client)
    out = await catalog_feed.pull_and_reconcile(session_factory, _FakeRedis())
    assert out["result"] == "unchanged"


@pytest.mark.asyncio
async def test_pull_never_raises(session_factory, monkeypatch):
    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url, headers=None):
            raise OSError("network down")

    monkeypatch.setattr(catalog_feed.httpx, "AsyncClient", _Client)
    out = await catalog_feed.pull_and_reconcile(session_factory, _FakeRedis())
    assert out["result"] == "error"


def test_feed_never_exposes_markup():
    """The markup multiplier is deployment business config — the public feed
    must serve pass-through pricing regardless of what the build bundles."""
    doc = catalog_feed.load_bundled_feed()
    for row in doc["pricing"]:
        assert float(row.get("markup_multiplier", 1)) == 1.0, row["model_tag"]
