from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mlpal_assistants_service.services.audio import AudioService
from mlpal_assistants_service.services.embedding import EmbeddingService
from mlpal_assistants_service.services.image import ImageService


class _SessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.parametrize(
    ("service_cls", "module_name", "kwargs"),
    [
        (ImageService, "image", {"asset_storage": None}),
        (AudioService, "audio", {"asset_storage": None}),
        (EmbeddingService, "embedding", {}),
    ],
)
@pytest.mark.asyncio
async def test_modality_background_debits_wallet_once(
    service_cls,
    module_name,
    kwargs,
) -> None:
    service = service_cls(session=MagicMock(), redis_client=None, **kwargs)
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
            f"mlpal_assistants_service.services.{module_name}.build_billing_gate",
            return_value=billing_repo,
        ),
        patch(
            f"mlpal_assistants_service.services.{module_name}.UsageService",
            return_value=usage_service,
        ),
    ):
        await service._post_request_background(
            user_id=1,
            api_key_id=2,
            trace_id=f"trace-{module_name}",
            resolved_model_tag="gpt-5.2",
            provider="openai",
            operation="embedding" if module_name == "embedding" else "image_generation",
            input_tokens=0,
            output_tokens=0,
            compute_units=Decimal("2.0"),
            latency_ms=50,
            billing_needs_ensure=False,
        )

    billing_repo.debit_wallet_usage.assert_awaited_once()
    usage_service.mark_wallet_debit_status.assert_awaited_once()


@pytest.mark.parametrize(
    ("service_cls", "module_name", "kwargs"),
    [
        (ImageService, "image", {"asset_storage": None}),
        (AudioService, "audio", {"asset_storage": None}),
        (EmbeddingService, "embedding", {}),
    ],
)
@pytest.mark.asyncio
async def test_modality_background_commits_retryable_wallet_failure(
    service_cls,
    module_name,
    kwargs,
) -> None:
    service = service_cls(session=MagicMock(), redis_client=None, **kwargs)
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
            f"mlpal_assistants_service.services.{module_name}.build_billing_gate",
            return_value=billing_repo,
        ),
        patch(
            f"mlpal_assistants_service.services.{module_name}.UsageService",
            return_value=usage_service,
        ),
    ):
        await service._post_request_background(
            user_id=1,
            api_key_id=2,
            trace_id=f"trace-{module_name}",
            resolved_model_tag="gpt-5.2",
            provider="openai",
            operation="embedding" if module_name == "embedding" else "image_generation",
            input_tokens=0,
            output_tokens=0,
            compute_units=Decimal("2.0"),
            latency_ms=50,
            billing_needs_ensure=False,
        )

    usage_service.mark_wallet_debit_status.assert_awaited_once_with(
        f"trace-{module_name}",
        "failed_retryable",
        error="payments down",
    )
    bg_session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    ("service_cls", "module_name", "kwargs"),
    [
        (ImageService, "image", {"asset_storage": None}),
        (AudioService, "audio", {"asset_storage": None}),
        (EmbeddingService, "embedding", {}),
    ],
)
@pytest.mark.asyncio
async def test_modality_background_marks_insufficient_wallet_failure_permanent(
    service_cls,
    module_name,
    kwargs,
) -> None:
    service = service_cls(session=MagicMock(), redis_client=None, **kwargs)
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
            f"mlpal_assistants_service.services.{module_name}.build_billing_gate",
            return_value=billing_repo,
        ),
        patch(
            f"mlpal_assistants_service.services.{module_name}.UsageService",
            return_value=usage_service,
        ),
    ):
        await service._post_request_background(
            user_id=1,
            api_key_id=2,
            trace_id=f"trace-{module_name}",
            resolved_model_tag="gpt-5.2",
            provider="openai",
            operation="embedding" if module_name == "embedding" else "image_generation",
            input_tokens=0,
            output_tokens=0,
            compute_units=Decimal("2.0"),
            latency_ms=50,
            billing_needs_ensure=False,
        )

    usage_service.mark_wallet_debit_status.assert_awaited_once_with(
        f"trace-{module_name}",
        "failed_permanent",
        error="insufficient wallet balance",
    )
    bg_session.commit.assert_awaited_once()
