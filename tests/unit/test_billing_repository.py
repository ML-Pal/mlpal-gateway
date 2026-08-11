"""Tests for BillingRepository - the API access gatekeeper.

These tests cover the critical can_make_request() logic that determines
whether a user can make API requests.
"""

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from mlpal_assistants_service.db.models import BillingStatus, UserBillingStatus
from mlpal_assistants_service.repositories.billing_repository import (
    BillingRepository,
    is_insufficient_wallet_error,
)


@pytest.fixture
def mock_session():
    """Mock async session."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def billing_repo(mock_session):
    """Create billing repository with mock session."""
    return BillingRepository(mock_session)


class TestWalletDebitKillSwitch:
    """The temporary MLPAL_WALLET_DEBIT_ENABLED kill switch must gate debits
    independently of the backend walletGatingEnabled flag."""

    @pytest.mark.asyncio
    async def test_debit_inactive_when_kill_switch_off_even_if_gating_on(
        self, billing_repo, monkeypatch
    ) -> None:
        billing_repo.is_wallet_gating_enabled = AsyncMock(return_value=True)
        monkeypatch.setattr(billing_repo._settings, "wallet_debit_enabled", False)

        assert await billing_repo.is_wallet_debit_active() is False
        # Short-circuits before the backend gating round-trip.
        billing_repo.is_wallet_gating_enabled.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_debit_active_requires_both_switches_on(
        self, billing_repo, monkeypatch
    ) -> None:
        monkeypatch.setattr(billing_repo._settings, "wallet_debit_enabled", True)
        billing_repo.is_wallet_gating_enabled = AsyncMock(return_value=True)
        assert await billing_repo.is_wallet_debit_active() is True

        billing_repo.is_wallet_gating_enabled = AsyncMock(return_value=False)
        assert await billing_repo.is_wallet_debit_active() is False


def create_billing_status(
    user_id: int = 1,
    status: str = BillingStatus.ACTIVE.value,
    spending_limit_cu: Decimal | None = None,
    current_period_cu: Decimal = Decimal("0"),
    suspended_reason: str | None = None,
) -> UserBillingStatus:
    """Helper to create a billing status object."""
    billing = UserBillingStatus(
        id=1,
        user_id=user_id,
        status=status,
        spending_limit_cu=spending_limit_cu,
        current_period_cu=current_period_cu,
        suspended_reason=suspended_reason,
    )
    return billing


class TestCanMakeRequest:
    """Tests for can_make_request() - the critical gatekeeper."""

    @pytest.mark.asyncio
    async def test_new_user_no_billing_status_allowed(self, billing_repo, mock_session):
        """New users with no billing status should be allowed."""
        # Mock: no billing status found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        can_request, reason = await billing_repo.can_make_request(user_id=999)

        assert can_request is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_active_user_allowed(self, billing_repo, mock_session):
        """Active users should be allowed."""
        billing = create_billing_status(status=BillingStatus.ACTIVE.value)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = billing
        mock_session.execute.return_value = mock_result

        can_request, reason = await billing_repo.can_make_request(user_id=1)

        assert can_request is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_suspended_user_blocked(self, billing_repo, mock_session):
        """Suspended users should be blocked with reason."""
        billing = create_billing_status(
            status=BillingStatus.SUSPENDED.value,
            suspended_reason="Payment overdue",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = billing
        mock_session.execute.return_value = mock_result

        can_request, reason = await billing_repo.can_make_request(user_id=1)

        assert can_request is False
        assert reason == "Payment overdue"

    @pytest.mark.asyncio
    async def test_blocked_user_blocked(self, billing_repo, mock_session):
        """Blocked users should be blocked."""
        billing = create_billing_status(status=BillingStatus.BLOCKED.value)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = billing
        mock_session.execute.return_value = mock_result

        can_request, reason = await billing_repo.can_make_request(user_id=1)

        assert can_request is False
        assert reason == "Account blocked"

    @pytest.mark.asyncio
    async def test_within_spending_limit_allowed(self, billing_repo, mock_session):
        """Users within spending limit should be allowed."""
        billing = create_billing_status(
            spending_limit_cu=Decimal("100.0"),
            current_period_cu=Decimal("50.0"),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = billing
        mock_session.execute.return_value = mock_result

        can_request, reason = await billing_repo.can_make_request(
            user_id=1,
            estimated_cu=Decimal("10.0"),
        )

        assert can_request is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_exceeds_spending_limit_blocked(self, billing_repo, mock_session):
        """Users exceeding spending limit should be blocked."""
        billing = create_billing_status(
            spending_limit_cu=Decimal("100.0"),
            current_period_cu=Decimal("95.0"),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = billing
        mock_session.execute.return_value = mock_result

        can_request, reason = await billing_repo.can_make_request(
            user_id=1,
            estimated_cu=Decimal("10.0"),  # Would exceed limit
        )

        assert can_request is False
        assert reason == "Monthly spending limit reached"

    @pytest.mark.asyncio
    async def test_no_spending_limit_unlimited(self, billing_repo, mock_session):
        """Users with no spending limit should have unlimited access."""
        billing = create_billing_status(
            spending_limit_cu=None,  # No limit
            current_period_cu=Decimal("10000.0"),  # High usage
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = billing
        mock_session.execute.return_value = mock_result

        can_request, reason = await billing_repo.can_make_request(
            user_id=1,
            estimated_cu=Decimal("1000.0"),
        )

        assert can_request is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_wallet_gate_disabled_allows_request(self, billing_repo, mock_session):
        billing_repo._get_wallet_gate_snapshot = AsyncMock(
            return_value={
                "wallet_gating_enabled": False,
                "wallet_access_status": "compatibility",
                "wallet_balance_cu": "0",
            }
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        can_request, reason, existed = await billing_repo.can_make_request_cached(1)

        assert can_request is True
        assert reason is None
        assert existed is False

    @pytest.mark.asyncio
    async def test_wallet_gate_disabled_still_honors_legacy_blocks(
        self,
        billing_repo,
        mock_session,
    ):
        billing_repo._get_wallet_gate_snapshot = AsyncMock(
            return_value={
                "wallet_gating_enabled": False,
                "wallet_access_status": "compatibility",
                "wallet_balance_cu": "0",
            }
        )
        blocked_status = create_billing_status(status=BillingStatus.BLOCKED.value)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = blocked_status
        mock_session.execute.return_value = mock_result

        can_request, reason, existed = await billing_repo.can_make_request_cached(1)

        assert can_request is False
        assert reason == "Account blocked"
        assert existed is True

    @pytest.mark.asyncio
    async def test_wallet_gate_blocks_zero_balance(self, billing_repo):
        billing_repo._get_wallet_gate_snapshot = AsyncMock(
            return_value={
                "wallet_gating_enabled": True,
                "wallet_access_status": "insufficient_balance",
                "wallet_balance_cu": "0",
            }
        )

        can_request, reason, existed = await billing_repo.can_make_request_cached(1)

        assert can_request is False
        assert "wallet" in reason.lower()
        assert existed is True

    @pytest.mark.asyncio
    async def test_wallet_debit_402_sets_soft_insufficient_balance_cache(self, mock_session):
        redis_client = MagicMock()
        redis_client.setex = AsyncMock()
        repo = BillingRepository(mock_session, redis_client=redis_client)

        request = httpx.Request("POST", "https://payments.test/api/v1/internal/wallet/debit")
        response = httpx.Response(
            402,
            request=request,
            json={"detail": "insufficient wallet balance"},
        )

        class _ClientContext:
            def __init__(self, response: httpx.Response):
                self._client = MagicMock()
                self._client.post = AsyncMock(return_value=response)

            async def __aenter__(self):
                return self._client

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            with pytest.MonkeyPatch.context() as monkeypatch:
                monkeypatch.setattr(
                    "mlpal_assistants_service.repositories.billing_repository.httpx.AsyncClient",
                    lambda *args, **kwargs: _ClientContext(response),
                )
                await repo.debit_wallet_usage(
                    user_id=7,
                    compute_units=Decimal("3.5"),
                    usage_ref="trace-7",
                )

        assert is_insufficient_wallet_error(exc_info.value) is True
        redis_client.setex.assert_awaited_once()
        _, _, payload = redis_client.setex.await_args.args
        assert json.loads(payload) == {
            "wallet_gating_enabled": True,
            "wallet_access_status": "insufficient_balance",
            "wallet_balance_cu": "0",
        }


class TestIsUserActive:
    """Tests for is_user_active()."""

    @pytest.mark.asyncio
    async def test_no_status_returns_true(self, billing_repo, mock_session):
        """No billing status means user is active (new user)."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        is_active = await billing_repo.is_user_active(user_id=999)

        assert is_active is True

    @pytest.mark.asyncio
    async def test_active_status_returns_true(self, billing_repo, mock_session):
        """Active status returns True."""
        billing = create_billing_status(status=BillingStatus.ACTIVE.value)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = billing
        mock_session.execute.return_value = mock_result

        is_active = await billing_repo.is_user_active(user_id=1)

        assert is_active is True

    @pytest.mark.asyncio
    async def test_suspended_status_returns_false(self, billing_repo, mock_session):
        """Suspended status returns False."""
        billing = create_billing_status(status=BillingStatus.SUSPENDED.value)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = billing
        mock_session.execute.return_value = mock_result

        is_active = await billing_repo.is_user_active(user_id=1)

        assert is_active is False
