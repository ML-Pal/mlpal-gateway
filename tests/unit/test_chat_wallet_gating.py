from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mlpal_assistants_service.services.chat import ChatService


class _SessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_chat_background_debits_wallet_once_after_usage_record() -> None:
    service = ChatService(session=MagicMock(), redis_client=None)
    bg_session = MagicMock()
    bg_session.commit = AsyncMock()

    billing_repo = MagicMock()
    billing_repo.is_wallet_gating_enabled = AsyncMock(return_value=True)
    billing_repo.is_wallet_debit_active = AsyncMock(return_value=True)
    billing_repo.debit_wallet_usage = AsyncMock(return_value=True)

    usage_service = MagicMock()
    usage_service.record_usage = AsyncMock()
    usage_service.mark_wallet_debit_status = AsyncMock()

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

    billing_repo.debit_wallet_usage.assert_awaited_once_with(
        user_id=1,
        compute_units=Decimal("3.5"),
        usage_ref="trace-1",
    )
    usage_service.record_usage.assert_awaited_once()
    usage_service.mark_wallet_debit_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_background_commits_retryable_wallet_failure() -> None:
    service = ChatService(session=MagicMock(), redis_client=None)
    bg_session = MagicMock()
    bg_session.commit = AsyncMock()

    billing_repo = MagicMock()
    billing_repo.is_wallet_gating_enabled = AsyncMock(return_value=True)
    billing_repo.is_wallet_debit_active = AsyncMock(return_value=True)
    billing_repo.debit_wallet_usage = AsyncMock(side_effect=RuntimeError("payments down"))

    usage_service = MagicMock()
    usage_service.record_usage = AsyncMock()
    usage_service.mark_wallet_debit_status = AsyncMock()

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

    usage_service.mark_wallet_debit_status.assert_awaited_once_with(
        "trace-1",
        "failed_retryable",
        error="payments down",
    )
    bg_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_background_marks_insufficient_wallet_failure_permanent() -> None:
    service = ChatService(session=MagicMock(), redis_client=None)
    bg_session = MagicMock()
    bg_session.commit = AsyncMock()

    request = httpx.Request("POST", "https://payments.test/api/v1/internal/wallet/debit")
    response = httpx.Response(
        402,
        request=request,
        json={"detail": "insufficient wallet balance"},
    )
    billing_repo = MagicMock()
    billing_repo.is_wallet_gating_enabled = AsyncMock(return_value=True)
    billing_repo.is_wallet_debit_active = AsyncMock(return_value=True)
    billing_repo.debit_wallet_usage = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "insufficient wallet balance",
            request=request,
            response=response,
        )
    )

    usage_service = MagicMock()
    usage_service.record_usage = AsyncMock()
    usage_service.mark_wallet_debit_status = AsyncMock()

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

    usage_service.mark_wallet_debit_status.assert_awaited_once_with(
        "trace-1",
        "failed_permanent",
        error="insufficient wallet balance",
    )
    bg_session.commit.assert_awaited_once()
