"""Self-scoped traces: the tenancy boundary and payload states.

Runs against real SQL (in-memory SQLite with the `assistants` schema translated
away) so the WHERE clauses are actually exercised, not mocked.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import BYTEA, JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles


# Postgres-only column types, rendered as their SQLite equivalents so
# Base.metadata.create_all works on the in-memory test engine.
@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "JSON"


@compiles(BYTEA, "sqlite")
def _bytea_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "BLOB"

from mlpal_assistants_service.db.models import APIKey, Base
from mlpal_assistants_service.db.models.usage_log import UsageLog
from mlpal_assistants_service.services.traces import query_traces

# usage_logs has a composite PK (id, created_at) for partitioning; SQLite can't
# AUTOINCREMENT that. DDL-only tweak for this test process — ids are explicit.
UsageLog.__table__.c.id.autoincrement = False
_next_id = iter(range(1, 10_000))


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={"schema_translate_map": {"assistants": None, "users": None, "mlpal_test": None}},
    )
    async with engine.begin() as conn:
        # Only the tables these tests touch — other models carry PG-only
        # constructs (composite autoincrement PKs) SQLite can't create.
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=[UsageLog.__table__, APIKey.__table__])
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _row(user_id: int, api_key_id: int, trace_id: str, *, status: str = "success",
         model: str = "claude-haiku-4-5-20251001", api: str | None = "v1_messages",
         age_hours: int = 1) -> UsageLog:
    return UsageLog(
        id=next(_next_id),
        user_id=user_id, api_key_id=api_key_id, trace_id=trace_id,
        model_tag=model, provider="anthropic", operation="chat",
        input_tokens=10, output_tokens=4, compute_units=Decimal("0.000003"),
        latency_ms=500, status=status, error_code=None if status == "success" else "http_500",
        wallet_debit_status="not_applicable",
        cc_metadata={"api": api} if api else {},
        created_at=datetime.now(UTC) - timedelta(hours=age_hours),
    )


@pytest_asyncio.fixture
async def seeded(session):
    session.add_all([
        _row(1, 10, "t-a1"),
        _row(1, 10, "t-a2", status="error", api="v2_messages"),
        _row(1, 11, "t-a3", model="gpt-5-nano", api=None),
        _row(2, 20, "t-b1"),  # another user's row — must never leak
    ])
    await session.commit()
    return session


@pytest.mark.asyncio
async def test_user_scope_is_absolute(seeded):
    out = await query_traces(seeded, user_id=1, limit=50)
    ids = {r["trace_id"] for r in out["data"]}
    assert ids == {"t-a1", "t-a2", "t-a3"} and out["total"] == 3
    assert "t-b1" not in ids  # user 2's row invisible to user 1

    out2 = await query_traces(seeded, user_id=2, limit=50)
    assert {r["trace_id"] for r in out2["data"]} == {"t-b1"}


@pytest.mark.asyncio
async def test_foreign_api_key_filter_yields_empty_not_leak(seeded):
    # user 1 asking for user 2's key id: empty page, no ownership oracle
    out = await query_traces(seeded, user_id=1, api_key_id=20, limit=50)
    assert out["total"] == 0 and out["data"] == []


@pytest.mark.asyncio
async def test_filters_compose(seeded):
    out = await query_traces(seeded, user_id=1, status="error", limit=50)
    assert [r["trace_id"] for r in out["data"]] == ["t-a2"]

    out = await query_traces(seeded, user_id=1, api="v1_messages", limit=50)
    assert [r["trace_id"] for r in out["data"]] == ["t-a1"]

    out = await query_traces(seeded, user_id=1, model_tag="gpt-5-nano", limit=50)
    assert [r["trace_id"] for r in out["data"]] == ["t-a3"]


@pytest.mark.asyncio
async def test_admin_global_view_is_explicit(seeded):
    out = await query_traces(seeded, user_id=None, limit=50)
    assert out["total"] == 4  # only the admin surface passes user_id=None


@pytest.mark.asyncio
async def test_row_shape(seeded):
    out = await query_traces(seeded, user_id=1, api="v2_messages", limit=50)
    r = out["data"][0]
    assert r["trace_id"] == "t-a2"
    assert r["api"] == "v2_messages"
    assert r["compute_units"] == pytest.approx(0.000003)
    assert set(r) >= {
        "trace_id", "created_at", "api_key_id", "api_key_name", "model_tag",
        "requested_model", "provider", "operation", "api", "input_tokens",
        "output_tokens", "compute_units", "latency_ms", "status", "error_code",
        "metadata",
    }
