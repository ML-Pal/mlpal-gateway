"""Retry pending wallet debit intents stored in usage logs."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mlpal_assistants_service.db.models import UsageLog
from mlpal_assistants_service.repositories.billing_repository import BillingRepository
from mlpal_assistants_service.seams.billing import is_insufficient_wallet_error
from mlpal_assistants_service.services.usage import UsageService


class DebitRetryWorker:
    """Replays retryable wallet debits using stable usage trace ids."""

    MAX_ATTEMPTS = 5

    def __init__(self, session: AsyncSession, redis_client=None) -> None:
        self._session = session
        self._billing = BillingRepository(session, redis_client)
        self._usage = UsageService(session, redis_client)

    async def run_once(self) -> int:
        # CU v3: if wallet debits are inactive — either the platform gating
        # flag is off or the service-level debit kill switch is set — any
        # usage_log left in pending/failed_retryable state is retired as
        # 'not_applicable' rather than retried. Retrying would produce the same
        # double-deduction the serving paths now avoid.
        debit_active = await self._billing.is_wallet_debit_active()
        result = await self._session.execute(
            select(UsageLog)
            .where(UsageLog.wallet_debit_status.in_(["pending", "failed_retryable"]))
            .with_for_update(skip_locked=True)
        )
        processed = 0
        for usage_log in result.scalars().all():
            if not debit_active:
                await self._usage.mark_wallet_debit_status(
                    usage_log.trace_id,
                    "not_applicable",
                    attempts=usage_log.wallet_debit_attempts,
                )
                processed += 1
                continue
            next_attempt = usage_log.wallet_debit_attempts + 1
            try:
                await self._billing.debit_wallet_usage(
                    user_id=usage_log.user_id,
                    compute_units=usage_log.compute_units,
                    usage_ref=usage_log.trace_id,
                )
                await self._usage.mark_wallet_debit_status(
                    usage_log.trace_id,
                    "debited",
                    attempts=next_attempt,
                )
                processed += 1
            except Exception as exc:  # noqa: BLE001
                status = (
                    "failed_permanent"
                    if is_insufficient_wallet_error(exc)
                    else (
                        "failed_permanent"
                        if next_attempt >= self.MAX_ATTEMPTS
                        else "failed_retryable"
                    )
                )
                await self._usage.mark_wallet_debit_status(
                    usage_log.trace_id,
                    status,
                    attempts=next_attempt,
                    error=str(exc),
                )
        await self._session.commit()
        return processed
