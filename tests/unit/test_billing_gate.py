"""Billing seam: the OSS local gate is allow-all with zero callout, the factory
selects by config, and the managed BillingRepository still satisfies the protocol."""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from mlpal_assistants_service.seams.billing import (
    BillingGate,
    LocalBillingGate,
    build_billing_gate,
    is_insufficient_wallet_error,
)


@pytest.mark.asyncio
async def test_local_gate_allows_all_and_never_debits():
    g = LocalBillingGate()
    allowed, reason, existed = await g.can_make_request_cached(7, Decimal("999999"))
    assert allowed is True and reason is None and existed is True  # no ensure scheduled
    assert await g.is_wallet_debit_active() is False
    assert await g.ensure_billing_status(7) is None
    assert await g.debit_wallet_usage(7, Decimal("5"), "ref") is True


def test_local_gate_satisfies_protocol():
    assert isinstance(LocalBillingGate(), BillingGate)


def test_factory_returns_local_for_oss_backend():
    gate = build_billing_gate(session=MagicMock(), redis=MagicMock(),
                              settings=SimpleNamespace(billing_backend="local"))
    assert isinstance(gate, LocalBillingGate)


@pytest.mark.asyncio
async def test_chat_service_wires_local_gate_in_oss_mode():
    """End-to-end: with billing_backend=local, ChatService binds the no-callout
    gate (this is what removes the hot-path 500 for self-hosters)."""
    from unittest.mock import patch

    from mlpal_assistants_service.services.chat import ChatService

    with patch("mlpal_assistants_service.seams.billing.get_settings",
               return_value=SimpleNamespace(billing_backend="local")):
        svc = ChatService(session=MagicMock(), redis_client=None)
    assert type(svc._billing).__name__ == "LocalBillingGate"
    allowed, reason, existed = await svc._billing.can_make_request_cached(1)
    assert allowed is True and existed is True  # allow-all, no ensure, no callout


def test_insufficient_wallet_error_classifies_402_only():
    # Lives on the seam so OSS services can import it without the managed module.
    req = httpx.Request("GET", "http://x")
    err_402 = httpx.HTTPStatusError("x", request=req, response=httpx.Response(402, request=req))
    err_403 = httpx.HTTPStatusError("x", request=req, response=httpx.Response(403, request=req))
    assert is_insufficient_wallet_error(err_402) is True
    assert is_insufficient_wallet_error(err_403) is False
    assert is_insufficient_wallet_error(ValueError("nope")) is False


def test_seam_import_does_not_pull_in_managed_wallet_module():
    """OSS import boundary: importing the billing seam must NOT import the
    managed payments/wallet repository. Run in a fresh interpreter so the check
    is not polluted by other tests that import billing_repository directly."""
    code = (
        "import sys; import mlpal_assistants_service.seams.billing as b;"
        "assert hasattr(b, 'is_insufficient_wallet_error');"
        "leaked = 'mlpal_assistants_service.repositories.billing_repository' in sys.modules;"
        "sys.exit(7 if leaked else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, (
        f"billing seam leaked the managed wallet module into the OSS import path "
        f"(rc={result.returncode}). stderr:\n{result.stderr}"
    )


def test_factory_returns_managed_by_default():
    # default / "managed" → the payments-integrated BillingRepository, which must
    # still satisfy the gate protocol structurally (managed path unchanged).
    gate = build_billing_gate(session=MagicMock(), redis=MagicMock(),
                              settings=SimpleNamespace(billing_backend="managed"))
    assert type(gate).__name__ == "BillingRepository"
    assert isinstance(gate, BillingGate)
    # a bare settings object with no attr also defaults to managed
    gate2 = build_billing_gate(session=MagicMock(), redis=MagicMock(),
                               settings=SimpleNamespace())
    assert type(gate2).__name__ == "BillingRepository"
