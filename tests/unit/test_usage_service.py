from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from mlpal_assistants_service.services.usage import UsageService


@pytest.mark.asyncio
async def test_pending_wallet_debit_usage_writes_directly_to_db() -> None:
    session = MagicMock()
    sqs_client = MagicMock()
    sqs_client.send_message = AsyncMock()
    service = UsageService(session, sqs_client=sqs_client)
    service.settings.sqs_usage_queue_url = "https://queue.example"
    service._write_usage_to_db = AsyncMock()

    await service.record_usage(
        user_id="1",
        api_key_id="2",
        trace_id="trace-1",
        model_tag="gpt-5.2",
        provider="openai",
        operation="chat",
        input_tokens=10,
        output_tokens=20,
        compute_units=Decimal("3.5"),
        wallet_debit_status="pending",
    )

    service._write_usage_to_db.assert_awaited_once()
    sqs_client.send_message.assert_not_awaited()
