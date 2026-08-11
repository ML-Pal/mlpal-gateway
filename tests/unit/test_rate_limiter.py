"""Unit tests for rate limiter."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from mlpal_assistants_service.core.exceptions import RateLimitExceededError
from mlpal_assistants_service.services.rate_limiter import (
    RATE_LIMIT_TIERS,
    RateLimiter,
)


class TestRateLimitTiers:
    """Tests for rate limit tier configuration."""

    def test_all_tiers_exist(self) -> None:
        """Test that all expected tiers are defined."""
        expected_tiers = ["free", "standard", "premium", "enterprise"]
        for tier in expected_tiers:
            assert tier in RATE_LIMIT_TIERS

    def test_tiers_have_increasing_limits(self) -> None:
        """Test that higher tiers have higher limits."""
        tiers_ordered = ["free", "standard", "premium", "enterprise"]

        for i in range(len(tiers_ordered) - 1):
            current = RATE_LIMIT_TIERS[tiers_ordered[i]]
            next_tier = RATE_LIMIT_TIERS[tiers_ordered[i + 1]]

            assert next_tier.requests_per_minute >= current.requests_per_minute
            assert next_tier.tokens_per_day >= current.tokens_per_day


class TestRateLimiter:
    """Tests for RateLimiter."""

    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        """Create mock Redis client."""
        redis = MagicMock()
        redis.zremrangebyscore = AsyncMock(return_value=0)
        redis.zcard = AsyncMock(return_value=0)
        redis.zadd = AsyncMock(return_value=1)
        redis.expire = AsyncMock(return_value=True)
        redis.zrange = AsyncMock(return_value=[])

        # Mock pipeline for batched operations
        mock_pipe = MagicMock()
        mock_pipe.zremrangebyscore = MagicMock(return_value=mock_pipe)
        mock_pipe.zcard = MagicMock(return_value=mock_pipe)
        mock_pipe.zadd = MagicMock(return_value=mock_pipe)
        mock_pipe.expire = MagicMock(return_value=mock_pipe)
        # Default: 0 count for both windows (zremrangebyscore result, zcard result x2)
        mock_pipe.execute = AsyncMock(return_value=[0, 0, 0, 0])
        redis.pipeline = MagicMock(return_value=mock_pipe)
        redis._mock_pipe = mock_pipe  # store for test access

        return redis

    @pytest.fixture
    def rate_limiter(self, mock_redis: MagicMock) -> RateLimiter:
        """Create rate limiter with mock Redis."""
        return RateLimiter(mock_redis)

    @pytest.mark.asyncio
    async def test_check_request_limit_allows_under_limit(
        self,
        rate_limiter: RateLimiter,
        mock_redis: MagicMock,
    ) -> None:
        """Test that requests under the limit are allowed."""
        # Mock returns 0 requests in window
        mock_redis.zcard.return_value = 0

        result = await rate_limiter.check_request_limit(
            user_id="test-user",
            tier="standard",
        )

        assert result.allowed is True
        assert result.remaining > 0

    @pytest.mark.asyncio
    async def test_check_request_limit_blocks_over_limit(
        self,
        rate_limiter: RateLimiter,
        mock_redis: MagicMock,
    ) -> None:
        """Test that requests over the limit are blocked."""
        # Mock pipeline returns minute count at limit
        standard_limit = RATE_LIMIT_TIERS["standard"].requests_per_minute
        mock_redis._mock_pipe.execute = AsyncMock(return_value=[0, standard_limit, 0, 0])

        with pytest.raises(RateLimitExceededError) as exc_info:
            await rate_limiter.check_request_limit(
                user_id="test-user",
                tier="standard",
            )

        assert exc_info.value.retry_after is not None
        assert exc_info.value.limit_type == "requests"

    @pytest.mark.asyncio
    async def test_check_request_limit_fails_open_on_redis_error(
        self,
        rate_limiter: RateLimiter,
        mock_redis: MagicMock,
    ) -> None:
        """A Redis outage must degrade to allowing the request, not 500 the API.

        Regression guard for INCIDENT 2026-06-03 (see ERRORS.md), where an
        exhausted Redis pool would otherwise have failed every limited request.
        """
        from redis.exceptions import ConnectionError as RedisConnectionError

        mock_redis._mock_pipe.execute = AsyncMock(
            side_effect=RedisConnectionError("Too many connections")
        )

        result = await rate_limiter.check_request_limit(
            user_id="test-user",
            tier="standard",
        )

        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_check_token_limit_allows_under_limit(
        self,
        rate_limiter: RateLimiter,
        mock_redis: MagicMock,
    ) -> None:
        """Test that token usage under the limit is allowed."""
        result = await rate_limiter.check_token_limit(
            user_id="test-user",
            tokens=1000,
            tier="standard",
        )

        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_check_token_limit_blocks_over_limit(
        self,
        rate_limiter: RateLimiter,
        mock_redis: MagicMock,
    ) -> None:
        """Test that token usage over the limit is blocked."""
        # Mock high token usage
        standard_limit = RATE_LIMIT_TIERS["standard"].tokens_per_minute
        mock_redis.zrange.return_value = [f"{standard_limit}:123456"]

        result = await rate_limiter.check_token_limit(
            user_id="test-user",
            tokens=1000,
            tier="standard",
        )

        assert result.allowed is False
        assert result.limit_type == "tokens"

    @pytest.mark.asyncio
    async def test_record_tokens_updates_redis(
        self,
        rate_limiter: RateLimiter,
        mock_redis: MagicMock,
    ) -> None:
        """Test that recording tokens updates Redis."""
        await rate_limiter.record_tokens(
            user_id="test-user",
            tokens=500,
        )

        # Should use pipeline with zadd + expire for both windows
        pipe = mock_redis._mock_pipe
        assert pipe.zadd.call_count == 2
        assert pipe.expire.call_count == 2
