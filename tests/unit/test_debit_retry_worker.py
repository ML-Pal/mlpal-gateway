from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from mlpal_assistants_service.services.debit_retry_worker import DebitRetryWorker


@pytest.mark.asyncio
async def test_retry_worker_claims_rows_with_skip_locked() -> None:
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    worker = DebitRetryWorker(session)
    worker._billing.is_wallet_gating_enabled = AsyncMock(return_value=True)

    await worker.run_once()

    statement = session.execute.await_args.args[0]
    assert statement._for_update_arg is not None
    assert statement._for_update_arg.skip_locked is True


@pytest.mark.asyncio
async def test_retry_worker_marks_insufficient_wallet_failures_permanent() -> None:
    usage_log = MagicMock(
        user_id=1,
        compute_units=3.5,
        trace_id="trace-1",
        wallet_debit_attempts=0,
    )
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [usage_log]
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    worker = DebitRetryWorker(session)
    worker._billing.is_wallet_gating_enabled = AsyncMock(return_value=True)
    request = httpx.Request("POST", "https://payments.test/api/v1/internal/wallet/debit")
    response = httpx.Response(
        402,
        request=request,
        json={"detail": "insufficient wallet balance"},
    )
    worker._billing.debit_wallet_usage = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "insufficient wallet balance",
            request=request,
            response=response,
        )
    )
    worker._usage.mark_wallet_debit_status = AsyncMock()

    processed = await worker.run_once()

    assert processed == 0
    worker._usage.mark_wallet_debit_status.assert_awaited_once_with(
        "trace-1",
        "failed_permanent",
        attempts=1,
        error="insufficient wallet balance",
    )
