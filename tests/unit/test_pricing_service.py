"""Unit tests for pricing service."""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from mlpal_assistants_service.services.pricing import PricingService


class TestPricingService:
    """Tests for PricingService."""

    @pytest.fixture
    def mock_session(self) -> MagicMock:
        """Create mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def service(self, mock_session: MagicMock) -> PricingService:
        """Create service with mock session."""
        return PricingService(mock_session, redis_client=None)

    @pytest.mark.asyncio
    async def test_calculate_default_cu(
        self,
        service: PricingService,
    ) -> None:
        """Test default compute unit calculation."""
        # Default: $1 per 1M input tokens, $2 per 1M output tokens, pass-through
        # (no markup), CU = dollars / cu_to_usd (10):
        # 500 in + 500 out = (500*1/1M + 500*2/1M) / 10
        result = service._calculate_default_cu(
            input_units=500,
            output_units=500,
        )

        assert isinstance(result, Decimal)
        # (0.0005 + 0.001) / 10 = 0.00015
        assert result == Decimal("0.00015")

    @pytest.mark.asyncio
    async def test_calculate_cu_with_different_token_counts(
        self,
        service: PricingService,
    ) -> None:
        """Test calculation with various token counts."""
        # 50 in + 50 out = (50/1M * 1 + 50/1M * 2) / 10 = 0.000015
        result1 = service._calculate_default_cu(
            input_units=50,
            output_units=50,
        )
        assert result1 == Decimal("0.000015")

        # 5000 in + 5000 out = (5000/1M * 1 + 5000/1M * 2) / 10 = 0.0015
        result2 = service._calculate_default_cu(
            input_units=5000,
            output_units=5000,
        )
        assert result2 == Decimal("0.0015")

    @pytest.mark.asyncio
    async def test_calculate_compute_units_uses_default_when_no_pricing(
        self,
        service: PricingService,
        mock_session: MagicMock,
    ) -> None:
        """Test that default pricing is used when model not in database."""
        # Mock execute to return None (no pricing found)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await service.calculate_compute_units(
            model_tag="unknown-model",
            input_units=500,
            output_units=500,
        )

        # Default fallback, pass-through: (500/1M * 1 + 500/1M * 2) / 10
        assert result == Decimal("0.00015")

    @pytest.mark.asyncio
    async def test_estimate_compute_units(
        self,
        service: PricingService,
        mock_session: MagicMock,
    ) -> None:
        """Test pre-request estimation."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Estimate for 1000 tokens (assumes 50/50 split)
        result = await service.estimate_compute_units(
            model_tag="gpt-5.2",
            estimated_tokens=1000,
        )

        assert isinstance(result, Decimal)

    @pytest.mark.asyncio
    async def test_clear_cache(
        self,
        service: PricingService,
    ) -> None:
        """Test cache clearing."""
        # Add something to cache via TTLCache API
        await service._local_cache.set("test", MagicMock())

        await service.clear_cache()

        assert service._local_cache.stats()["total_entries"] == 0
