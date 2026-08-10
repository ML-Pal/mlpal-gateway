"""Circuit breaker: throttling (429/quota/overloaded) must NOT open the breaker,
but genuine faults (5xx / timeouts / connection errors) still do.

The breaker is per-provider, so counting a rate-limit burst as a failure would let
one caller's throttling fail-fast every caller. Throttling is transient and handled
by per-request retry+backoff; only real provider faults should trip the breaker.
"""

from __future__ import annotations

import pytest

from mlpal_assistants_service.adapters.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpen,
    CircuitState,
)
from mlpal_assistants_service.core.exceptions import (
    ProviderError,
    ProviderUnavailableError,
)


def _breaker() -> CircuitBreaker:
    return CircuitBreaker(provider="openai", config=CircuitBreakerConfig(failure_threshold=5))


async def _run(breaker: CircuitBreaker, exc: Exception | None) -> None:
    try:
        async with breaker:
            if exc is not None:
                raise exc
    except (ProviderError, ProviderUnavailableError):
        pass


@pytest.mark.asyncio
async def test_throttling_never_opens_breaker():
    b = _breaker()
    # Far more than failure_threshold consecutive 429s.
    for _ in range(20):
        await _run(b, ProviderUnavailableError("rate limited", provider="openai"))
    assert b.state == CircuitState.CLOSED
    assert b.stats.consecutive_failures == 0
    assert b.stats.throttled_calls == 20


@pytest.mark.asyncio
async def test_genuine_faults_still_open_breaker():
    b = _breaker()
    for _ in range(5):  # == failure_threshold
        await _run(b, ProviderError("500 internal", provider="openai", status_code=500))
    assert b.state == CircuitState.OPEN
    # Once OPEN, further calls fast-fail with CircuitBreakerOpen.
    with pytest.raises(CircuitBreakerOpen):
        async with b:
            pass


@pytest.mark.asyncio
async def test_throttling_does_not_reset_a_real_failure_streak():
    # Throttling is NEUTRAL: it neither trips nor heals the breaker. A couple of
    # real faults, a 429 in between, then more real faults should still open it.
    b = _breaker()
    for _ in range(3):
        await _run(b, ProviderError("timeout", provider="openai", status_code=504))
    await _run(b, ProviderUnavailableError("overloaded", provider="openai"))  # neutral
    assert b.stats.consecutive_failures == 3  # not reset by the throttle
    for _ in range(2):
        await _run(b, ProviderError("timeout", provider="openai", status_code=504))
    assert b.state == CircuitState.OPEN  # 3 + 2 real faults reached the threshold


@pytest.mark.asyncio
async def test_success_closes_the_streak():
    b = _breaker()
    for _ in range(4):
        await _run(b, ProviderError("500", provider="openai", status_code=500))
    await _run(b, None)  # success resets
    assert b.stats.consecutive_failures == 0
    assert b.state == CircuitState.CLOSED
