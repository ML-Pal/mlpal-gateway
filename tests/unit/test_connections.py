"""Connections: custody drivers, byok overlay precedence, byom model overlay,
tenant pool, egress guard, wallet skip.

Contract (planning/designs/connections-byom.md): raw keys never persist in
the gateway; byok creds outrank deployment creds with azure > first_party
precedence; invalid creds fall out of serving (deployment keys = no
downtime); users without connections pay only a cached dict probe;
connection-served requests never touch the wallet; `user/…` tags resolve
per-tenant and never through shared caches.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from mlpal_assistants_service.core.config import get_settings
from mlpal_assistants_service.seams.custody import LocalDriver
from mlpal_assistants_service.services import connections as conn_svc


@pytest.fixture(autouse=True)
def _clean():
    conn_svc.clear_pool()
    yield
    conn_svc.clear_pool()


# ── custody: local driver ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_local_driver_roundtrip_and_tenant_binding():
    import base64
    import os

    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    d = LocalDriver(key)
    ref = await d.store(42, "gateway-conn-anthropic-first_party", "sk-ant-secret")
    assert "sk-ant-secret" not in ref  # ciphertext only
    assert await d.reveal(42, ref) == "sk-ant-secret"
    # AAD binds the tenant: another user's id must not decrypt this ref.
    from cryptography.exceptions import InvalidTag

    with pytest.raises(InvalidTag):
        await d.reveal(43, ref)


def test_local_driver_rejects_bad_key_length():
    with pytest.raises(ValueError):
        LocalDriver("dG9vc2hvcnQ")  # "tooshort"


# ── fakes ────────────────────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, stmt):
        return _FakeResult(self.rows)


def _row(**kw):
    base = {
        "id": 1, "user_id": 7, "kind": "byok", "name": None,
        "family": "anthropic", "backend": "first_party",
        "secret_ref": "local:v1:x:y", "driver": "local", "status": "verified",
        "error": None, "fallback": "mlpal", "config": None,
        "updated_at": datetime(2026, 8, 19),
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _model_row(**kw):
    base = {
        "id": 1, "user_id": 7, "connection_id": 9, "model_tag": "user/my-llama",
        "provider_model_id": "llama-3.1-8b", "operation": "chat",
        "context_length": 32768, "max_output_tokens": 4096,
        "input_price_per_m": Decimal("0.20"), "output_price_per_m": Decimal("0.60"),
        "capabilities": None, "is_active": True,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _byom_conn_row(**kw):
    base = {
        "id": 9, "user_id": 7, "kind": "byom", "name": "my-box",
        "family": "openai", "backend": "custom", "secret_ref": "local:v1:x:y",
        "driver": "local", "status": "verified", "error": None,
        "fallback": "none", "config": {"endpoint": "http://localhost:9/v1"},
        "updated_at": datetime(2026, 8, 19),
    }
    base.update(kw)
    return SimpleNamespace(**base)


# ── byok overlay ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_overlay_precedence_azure_over_first_party():
    rows = [
        _row(id=1, family="openai", backend="first_party"),
        _row(id=2, family="openai", backend="azure",
             config={"endpoint": "https://r.services.ai.azure.com"}),
    ]
    overlay = await conn_svc.get_overlay(7, _FakeSession(rows))
    assert [c.backend for c in overlay["openai"]] == ["azure", "first_party"]


@pytest.mark.asyncio
async def test_overlay_keeps_invalid_marked_and_drops_unsupported():
    """Invalid creds stay in the overlay (marked) so fallback='none' can
    BLOCK; serving itself skips them. Unsupported targets are dropped."""
    rows = [
        _row(id=1, status="invalid"),
        _row(id=2, family="anthropic", backend="vertex"),  # unsupported in v1
    ]
    overlay = await conn_svc.get_overlay(7, _FakeSession(rows))
    assert [c.status for c in overlay["anthropic"]] == ["invalid"]
    # serving skips the invalid cred → falls to deployment (fallback=mlpal)
    assert await conn_svc.resolve_tenant_adapter(7, _FakeSession(rows), "anthropic", "x") is None


@pytest.mark.asyncio
async def test_fallback_none_blocks_instead_of_billing(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "connections_enabled", True)
    rows = [_row(id=1, status="invalid", fallback="none")]
    with pytest.raises(conn_svc.ConnectionBlocked):
        await conn_svc.resolve_tenant_adapter(7, _FakeSession(rows), "anthropic", "x")
    conn_svc.clear_pool()
    # fallback="mlpal" on the same failure degrades silently instead
    rows2 = [_row(id=1, status="invalid", fallback="mlpal")]
    assert await conn_svc.resolve_tenant_adapter(7, _FakeSession(rows2), "anthropic", "x") is None


@pytest.mark.asyncio
async def test_overlay_negative_result_cached(monkeypatch):
    session = _FakeSession([])
    calls = {"n": 0}
    orig = session.execute

    async def counting(stmt):
        calls["n"] += 1
        return await orig(stmt)

    session.execute = counting
    await conn_svc.get_overlay(7, session)
    await conn_svc.get_overlay(7, session)
    assert calls["n"] == 1  # second hit served from cache


# ── resolve_tenant_adapter (byok) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolver_disabled_by_default_and_never_raises(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "connections_enabled", False)
    assert await conn_svc.resolve_tenant_adapter(7, _FakeSession([]), "anthropic", "x") is None

    monkeypatch.setattr(s, "connections_enabled", True)

    class Boom:
        async def execute(self, stmt):
            raise RuntimeError("db down")

    # Overlay failure degrades to deployment path, never raises.
    assert await conn_svc.resolve_tenant_adapter(7, Boom(), "anthropic", "x") is None


@pytest.mark.asyncio
async def test_resolver_builds_pooled_tenant_adapter(monkeypatch):
    import base64
    import os

    s = get_settings()
    monkeypatch.setattr(s, "connections_enabled", True)
    monkeypatch.setattr(s, "custody_driver", "local")
    monkeypatch.setattr(
        s, "custody_local_key", base64.urlsafe_b64encode(os.urandom(32)).decode()
    )
    from mlpal_assistants_service.seams.custody import build_custody

    ref = await build_custody(s).store(7, "n", "sk-ant-tenant-key")
    rows = [_row(secret_ref=ref)]
    got = await conn_svc.resolve_tenant_adapter(7, _FakeSession(rows), "anthropic", "claude-opus-5")
    assert got is not None
    adapter, wire_id, conn = got
    assert wire_id == "claude-opus-5" and conn.id == 1
    assert adapter._api_key == "sk-ant-tenant-key"
    # pooled: same object back, no second reveal
    got2 = await conn_svc.resolve_tenant_adapter(7, _FakeSession(rows), "anthropic", "claude-opus-5")
    assert got2[0] is adapter


@pytest.mark.asyncio
async def test_azure_tenant_adapter_maps_deployments(monkeypatch):
    import base64
    import os

    s = get_settings()
    monkeypatch.setattr(s, "connections_enabled", True)
    monkeypatch.setattr(s, "custody_driver", "local")
    monkeypatch.setattr(
        s, "custody_local_key", base64.urlsafe_b64encode(os.urandom(32)).decode()
    )
    from mlpal_assistants_service.seams.custody import build_custody

    ref = await build_custody(s).store(7, "n", "az-key")
    rows = [
        _row(
            id=5, family="openai", backend="azure", secret_ref=ref,
            config={"endpoint": "https://r.services.ai.azure.com",
                    "deployments": {"gpt-5-mini": "their-mini"}},
        )
    ]
    got = await conn_svc.resolve_tenant_adapter(7, _FakeSession(rows), "openai", "gpt-5-mini")
    assert got is not None
    adapter, wire_id, conn = got
    assert wire_id == "their-mini"
    assert adapter.backend_name == "azure"
    assert str(adapter._client.base_url).startswith("https://r.services.ai.azure.com/openai/v1")
    # model outside their deployments -> None (deployment keys serve it)
    assert await conn_svc.resolve_tenant_adapter(7, _FakeSession(rows), "openai", "gpt-5.2") is None


# ── byom: namespace, model overlay, resolution, estimate ───────────────────


def test_user_tag_namespace():
    ok = ["user/llama3-ft", "user/x", "user/a.b_c-1"]
    bad = ["user/", "user/UPPER", "gpt-5", "user//x", "users/x", "user/-x"]
    for t in ok:
        assert conn_svc.USER_TAG_RE.match(t), t
    for t in bad:
        assert not conn_svc.USER_TAG_RE.match(t), t


@pytest.mark.asyncio
async def test_resolve_tenant_model_serves_user_tag(monkeypatch):
    import base64
    import os

    s = get_settings()
    monkeypatch.setattr(s, "connections_enabled", True)
    monkeypatch.setattr(s, "environment", "development")  # allow localhost endpoint
    monkeypatch.setattr(s, "custody_driver", "local")
    monkeypatch.setattr(
        s, "custody_local_key", base64.urlsafe_b64encode(os.urandom(32)).decode()
    )
    from mlpal_assistants_service.seams.custody import build_custody

    ref = await build_custody(s).store(7, "n", "their-endpoint-key")
    rows = [(_model_row(), _byom_conn_row(secret_ref=ref))]
    got = await conn_svc.resolve_tenant_model(7, _FakeSession(rows), "user/my-llama")
    assert got is not None
    adapter, wire_id, model_ref = got
    assert wire_id == "llama-3.1-8b"
    assert adapter.backend_name == "custom"
    assert str(adapter._client.base_url).startswith("http://localhost:9/v1")
    assert adapter.serves("anything") and adapter.backend_model_id("x") == "x"
    # unknown tag → None (reads as model-not-found upstream)
    assert await conn_svc.resolve_tenant_model(7, _FakeSession(rows), "user/nope") is None


@pytest.mark.asyncio
async def test_resolve_tenant_model_gates(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "connections_enabled", False)
    rows = [(_model_row(), _byom_conn_row())]
    # feature off → None
    assert await conn_svc.resolve_tenant_model(7, _FakeSession(rows), "user/my-llama") is None
    monkeypatch.setattr(s, "connections_enabled", True)
    # invalid connection → None (attributed on the row, not served)
    rows_bad = [(_model_row(), _byom_conn_row(status="invalid"))]
    assert await conn_svc.resolve_tenant_model(7, _FakeSession(rows_bad), "user/my-llama") is None
    # non-user tag → None without any I/O
    assert await conn_svc.resolve_tenant_model(7, _FakeSession([]), "gpt-5.2") is None


def test_byom_usd_estimate_uses_declared_prices():
    ref = SimpleNamespace(
        input_price_per_m=Decimal("0.20"), output_price_per_m=Decimal("0.60")
    )
    usd = conn_svc.byom_usd_estimate(ref, tokens_in=1_000_000, tokens_out=500_000)
    assert usd == Decimal("0.50")  # 0.20 + 0.30


# ── egress guard ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_egress_guard_blocks_private_and_requires_https(monkeypatch):
    from mlpal_assistants_service.seams.egress_guard import (
        EndpointRejected,
        validate_endpoint,
    )

    s = get_settings()
    monkeypatch.setattr(s, "environment", "production")
    with pytest.raises(EndpointRejected):  # scheme
        await validate_endpoint("http://api.example.com/v1")
    with pytest.raises(EndpointRejected):  # embedded credentials
        await validate_endpoint("https://user:pw@api.example.com/v1")
    with pytest.raises(EndpointRejected):  # loopback blocked outside dev
        await validate_endpoint("https://localhost/v1")

    # development: loopback + http allowed (local vLLM/Ollama rigs)
    monkeypatch.setattr(s, "environment", "development")
    await validate_endpoint("http://localhost:8081/v1")
