"""Regression tests for CacheInvalidator pub/sub connection handling.

Guards against INCIDENT 2026-06-03 (see ERRORS.md): the listener reconnected
without closing the previous pub/sub object, leaking SUBSCRIBE connections until
the shared Redis pool was exhausted. These tests assert that every pub/sub
connection is released on every reconnect, and that the dedicated pub/sub client
is used so the command pool can never be starved.
"""

import asyncio

import pytest

from mlpal_assistants_service.core.cache import CacheInvalidator


class _FakePubSub:
    def __init__(self, owner: "_FakeRedis") -> None:
        self._owner = owner

    async def subscribe(self, channel: str) -> None:
        self._owner.subscribed += 1

    async def aclose(self) -> None:
        self._owner.aclosed += 1

    async def listen(self):
        # Each connect immediately fails to force a reconnect, except the last
        # one which breaks the loop via cancellation. Mirrors a flapping link.
        self._owner.listens += 1
        if self._owner.listens >= self._owner.stop_after:
            raise asyncio.CancelledError()
        raise ConnectionError("simulated drop")
        yield  # pragma: no cover - marks this as an async generator


class _FakeRedis:
    """Minimal stand-in that counts pub/sub creates, subscribes and closes."""

    def __init__(self, stop_after: int) -> None:
        self.stop_after = stop_after
        self.created = 0
        self.subscribed = 0
        self.aclosed = 0
        self.listens = 0

    def pubsub(self) -> _FakePubSub:
        self.created += 1
        return _FakePubSub(self)


@pytest.mark.asyncio
async def test_listener_releases_every_connection_across_reconnects() -> None:
    pubsub_client = _FakeRedis(stop_after=4)
    command_client = _FakeRedis(stop_after=999)  # must never be touched

    invalidator = CacheInvalidator(command_client, pubsub_client=pubsub_client)
    # Make reconnect backoff negligible so the test is fast and deterministic.
    invalidator._INITIAL_BACKOFF = 0.0
    invalidator._MAX_BACKOFF = 0.0

    await asyncio.wait_for(invalidator._listen_loop(), timeout=5)

    # Every pub/sub connection that was created and subscribed was also closed:
    # zero leaked connections, which is the whole point.
    assert pubsub_client.created == pubsub_client.aclosed == 4
    assert pubsub_client.subscribed == 4
    # The command client's pool is never used for the subscriber.
    assert command_client.created == 0


@pytest.mark.asyncio
async def test_listener_falls_back_to_command_client_when_no_dedicated_client() -> None:
    command_client = _FakeRedis(stop_after=2)

    invalidator = CacheInvalidator(command_client)  # no dedicated pub/sub client
    invalidator._INITIAL_BACKOFF = 0.0
    invalidator._MAX_BACKOFF = 0.0

    await asyncio.wait_for(invalidator._listen_loop(), timeout=5)

    assert command_client.created == command_client.aclosed == 2
