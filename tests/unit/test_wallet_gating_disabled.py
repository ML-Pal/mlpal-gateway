"""Tests covering the POC guarantee that wallet debits are skipped
when wallet gating is disabled in the backend platform config.

Rationale: CU v3 POC shows the user an effective balance as
``wallet.balance - sum(cu_usage_aggregates)``. If assistants-service
also debits the wallet per request, the UI would subtract the usage
twice (once via the wallet balance that has already been debited, once
via the CU aggregates). This suite locks in the contract that when the
backend platform config has ``walletGatingEnabled=false``, every
serving path must:

  (a) NOT call ``debit_wallet_usage``,
  (b) mark the usage_log ``wallet_debit_status = not_applicable`` so
      the row is not picked up by the retry worker.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mlpal_assistants_service.services.chat import ChatService


class _SessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _build_billing_repo(*, gating_enabled: bool) -> MagicMock:
    repo = MagicMock()
    repo.is_wallet_gating_enabled = AsyncMock(return_value=gating_enabled)
    repo.is_wallet_debit_active = AsyncMock(return_value=gating_enabled)
    repo.debit_wallet_usage = AsyncMock(return_value=True)
    repo.ensure_billing_status = AsyncMock()
    return repo


def _build_usage_service() -> MagicMock:
    usage = MagicMock()
    usage.record_usage = AsyncMock()
    usage.mark_wallet_debit_status = AsyncMock()
    return usage


@pytest.mark.asyncio
async def test_chat_background_skips_wallet_debit_when_gating_disabled() -> None:
    service = ChatService(session=MagicMock(), redis_client=None)
    bg_session = MagicMock()
    bg_session.commit = AsyncMock()

    billing_repo = _build_billing_repo(gating_enabled=False)
    usage_service = _build_usage_service()

    with (
        patch(
            "mlpal_assistants_service.db.session.async_session_factory",
            return_value=_SessionContext(bg_session),
        ),
        patch(
            "mlpal_assistants_service.services.chat.build_billing_gate",
            return_value=billing_repo,
        ),
        patch(
            "mlpal_assistants_service.services.chat.UsageService",
            return_value=usage_service,
        ),
    ):
        await service._post_request_background(
            user_id=1,
            api_key_id=2,
            trace_id="trace-1",
            resolved_model_tag="gpt-5.2",
            provider="openai",
            input_tokens=10,
            output_tokens=20,
            compute_units=Decimal("3.5"),
            latency_ms=100,
            billing_needs_ensure=False,
        )

    billing_repo.debit_wallet_usage.assert_not_awaited()
    usage_service.mark_wallet_debit_status.assert_awaited_once_with(
        "trace-1",
        "not_applicable",
    )
    bg_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_background_still_debits_when_gating_enabled() -> None:
    """Regression guard — the skip must be keyed on the config flag only."""
    service = ChatService(session=MagicMock(), redis_client=None)
    bg_session = MagicMock()
    bg_session.commit = AsyncMock()

    billing_repo = _build_billing_repo(gating_enabled=True)
    usage_service = _build_usage_service()

    with (
        patch(
            "mlpal_assistants_service.db.session.async_session_factory",
            return_value=_SessionContext(bg_session),
        ),
        patch(
            "mlpal_assistants_service.services.chat.build_billing_gate",
            return_value=billing_repo,
        ),
        patch(
            "mlpal_assistants_service.services.chat.UsageService",
            return_value=usage_service,
        ),
    ):
        await service._post_request_background(
            user_id=1,
            api_key_id=2,
            trace_id="trace-2",
            resolved_model_tag="gpt-5.2",
            provider="openai",
            input_tokens=10,
            output_tokens=20,
            compute_units=Decimal("3.5"),
            latency_ms=100,
            billing_needs_ensure=False,
        )

    billing_repo.debit_wallet_usage.assert_awaited_once()
    usage_service.mark_wallet_debit_status.assert_awaited_once_with(
        "trace-2",
        "debited",
    )
