"""Rate limiting service using Redis sliding window."""

import logging
import time
from dataclasses import dataclass
from typing import Literal

import redis.asyncio as redis
from redis.exceptions import RedisError

from mlpal_assistants_service.core.exceptions import RateLimitExceededError

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Rate limit configuration for a tier."""

    requests_per_minute: int
    requests_per_hour: int
    tokens_per_minute: int
    tokens_per_day: int


# Rate limit tiers
RATE_LIMIT_TIERS: dict[str, RateLimitConfig] = {
    # Limits raised to favour client concurrency. `free` stays modest for abuse
    # protection; paid tiers get ~5x request headroom with tokens bumped in step
    # so throughput isn't re-bottlenecked by the token window. Per-user, sliding
    # window, fail-open.
    "free": RateLimitConfig(
        requests_per_minute=30,
        requests_per_hour=300,
        tokens_per_minute=20_000,
        tokens_per_day=200_000,
    ),
    "standard": RateLimitConfig(
        requests_per_minute=300,
        requests_per_hour=6000,
        tokens_per_minute=500_000,
        tokens_per_day=5_000_000,
    ),
    "premium": RateLimitConfig(
        requests_per_minute=1500,
        requests_per_hour=30000,
        tokens_per_minute=2_500_000,
        tokens_per_day=50_000_000,
    ),
    "enterprise": RateLimitConfig(
        requests_per_minute=6000,
        requests_per_hour=120000,
        tokens_per_minute=10_000_000,
        tokens_per_day=250_000_000,
    ),
}


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    limit: int
    remaining: int
    reset_at: float  # Unix timestamp
    limit_type: str  # "requests" or "tokens"
    window: str  # "minute", "hour", "day"


class RateLimiter:
    """
    Sliding window rate limiter using Redis sorted sets.

    Implements multi-window rate limiting:
    - Requests per minute
    - Requests per hour
    - Tokens per minute
    - Tokens per day
    """

    def __init__(self, redis_client: redis.Redis) -> None:
        self.redis = redis_client

    async def check_request_limit(
        self,
        user_id: str,
        tier: str = "standard",
    ) -> RateLimitResult:
        """
        Check if a request is allowed under rate limits.

        Args:
            user_id: User identifier
            tier: Rate limit tier

        Returns:
            RateLimitResult with allowed status and limit info

        Raises:
            RateLimitExceededError: If rate limit is exceeded
        """
        config = RATE_LIMIT_TIERS.get(tier, RATE_LIMIT_TIERS["standard"])
        now = time.time()

        minute_key = f"ratelimit:{user_id}:requests:minute"
        hour_key = f"ratelimit:{user_id}:requests:hour"

        # Rate limiting is best-effort: if Redis is unavailable we fail OPEN
        # (allow the request) rather than failing the API. The degradation is
        # logged with a stable event so it is distinguishable from a real
        # rejection and can be alerted on.
        try:
            # Batch both window checks into a single pipeline round-trip
            pipe = self.redis.pipeline(transaction=False)
            pipe.zremrangebyscore(minute_key, 0, now - 60)
            pipe.zcard(minute_key)
            pipe.zremrangebyscore(hour_key, 0, now - 3600)
            pipe.zcard(hour_key)
            results = await pipe.execute()

            minute_count = results[1]
            hour_count = results[3]

            if minute_count >= config.requests_per_minute:
                raise RateLimitExceededError(
                    message="Rate limit exceeded",
                    retry_after=60,
                    limit_type="requests",
                )

            if hour_count >= config.requests_per_hour:
                raise RateLimitExceededError(
                    message="Hourly rate limit exceeded",
                    retry_after=3600,
                    limit_type="requests",
                )

            # Increment counters in a single pipeline
            member = f"1:{now}"
            pipe2 = self.redis.pipeline(transaction=False)
            pipe2.zadd(minute_key, {member: now})
            pipe2.expire(minute_key, 61)
            pipe2.zadd(hour_key, {member: now})
            pipe2.expire(hour_key, 3601)
            await pipe2.execute()
        except RedisError as e:
            logger.warning(
                "rate_limiter_degraded: failing open on Redis error",
                extra={"user_id": user_id, "error": str(e)},
            )
            minute_count = 0

        return RateLimitResult(
            allowed=True,
            limit=config.requests_per_minute,
            remaining=max(0, config.requests_per_minute - minute_count - 1),
            reset_at=now + 60,
            limit_type="requests",
            window="minute",
        )

    async def check_token_limit(
        self,
        user_id: str,
        tokens: int,
        tier: str = "standard",
    ) -> RateLimitResult:
        """
        Check if token usage is within limits.

        Args:
            user_id: User identifier
            tokens: Number of tokens to check
            tier: Rate limit tier

        Returns:
            RateLimitResult
        """
        config = RATE_LIMIT_TIERS.get(tier, RATE_LIMIT_TIERS["standard"])
        now = time.time()

        # Check minute token limit
        minute_key = f"ratelimit:{user_id}:tokens:minute"
        minute_usage = await self._get_window_total(minute_key, 60, now)

        if minute_usage + tokens > config.tokens_per_minute:
            return RateLimitResult(
                allowed=False,
                limit=config.tokens_per_minute,
                remaining=max(0, config.tokens_per_minute - int(minute_usage)),
                reset_at=now + 60,
                limit_type="tokens",
                window="minute",
            )

        # Check daily token limit
        day_key = f"ratelimit:{user_id}:tokens:day"
        day_usage = await self._get_window_total(day_key, 86400, now)

        if day_usage + tokens > config.tokens_per_day:
            return RateLimitResult(
                allowed=False,
                limit=config.tokens_per_day,
                remaining=max(0, config.tokens_per_day - int(day_usage)),
                reset_at=now + 86400,
                limit_type="tokens",
                window="day",
            )

        return RateLimitResult(
            allowed=True,
            limit=config.tokens_per_minute,
            remaining=config.tokens_per_minute - int(minute_usage) - tokens,
            reset_at=now + 60,
            limit_type="tokens",
            window="minute",
        )

    async def record_tokens(
        self,
        user_id: str,
        tokens: int,
    ) -> None:
        """Record token usage after a request completes."""
        now = time.time()
        member = f"{tokens}:{now}"
        minute_key = f"ratelimit:{user_id}:tokens:minute"
        day_key = f"ratelimit:{user_id}:tokens:day"

        # Batch both windows into a single pipeline. Best-effort accounting:
        # a Redis outage must not fail the request that already succeeded.
        try:
            pipe = self.redis.pipeline(transaction=False)
            pipe.zadd(minute_key, {member: now})
            pipe.expire(minute_key, 61)
            pipe.zadd(day_key, {member: now})
            pipe.expire(day_key, 86401)
            await pipe.execute()
        except RedisError as e:
            logger.warning(
                "rate_limiter_degraded: token recording skipped on Redis error",
                extra={"user_id": user_id, "error": str(e)},
            )

    async def _check_window(
        self,
        key: str,
        limit: int,
        window_seconds: int,
        now: float,
    ) -> RateLimitResult:
        """Check a single rate limit window."""
        count = await self._get_window_count(key, window_seconds, now)

        window_name = "minute" if window_seconds == 60 else "hour" if window_seconds == 3600 else "day"

        return RateLimitResult(
            allowed=count < limit,
            limit=limit,
            remaining=max(0, limit - count - 1),
            reset_at=now + window_seconds,
            limit_type="requests",
            window=window_name,
        )

    async def _get_window_count(
        self,
        key: str,
        window_seconds: int,
        now: float,
    ) -> int:
        """Get the count of items in a sliding window."""
        window_start = now - window_seconds

        # Remove old entries
        await self.redis.zremrangebyscore(key, 0, window_start)

        # Count remaining
        return await self.redis.zcard(key)

    async def _get_window_total(
        self,
        key: str,
        window_seconds: int,
        now: float,
    ) -> float:
        """Get the sum of values in a sliding window (for token counting)."""
        window_start = now - window_seconds

        # Remove old entries
        await self.redis.zremrangebyscore(key, 0, window_start)

        # Get all entries and sum their values (stored in member name as "value:timestamp")
        entries = await self.redis.zrange(key, 0, -1)
        total = 0.0
        for entry in entries:
            if isinstance(entry, bytes):
                entry = entry.decode()
            parts = entry.split(":")
            if len(parts) >= 1:
                try:
                    total += float(parts[0])
                except ValueError:
                    pass
        return total

    async def _increment_window(
        self,
        key: str,
        window_seconds: int,
        now: float,
        increment: int = 1,
    ) -> None:
        """Add an entry to a sliding window."""
        # Store as "value:timestamp" to allow summing for token counts
        member = f"{increment}:{now}"
        await self.redis.zadd(key, {member: now})
        await self.redis.expire(key, window_seconds + 1)
