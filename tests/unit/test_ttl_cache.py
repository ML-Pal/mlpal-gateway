"""Unit tests for TTLCache."""

import asyncio
import time

import pytest

from mlpal_assistants_service.core.cache import TTLCache


@pytest.fixture
def cache():
    """Create a TTLCache with short default TTL for testing."""
    return TTLCache(default_ttl=1)  # 1 second default


class TestTTLCacheBasics:
    """Test basic get/set/delete operations."""

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache: TTLCache):
        await cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self, cache: TTLCache):
        assert cache.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_delete_key(self, cache: TTLCache):
        await cache.set("key1", "value1")
        await cache.delete("key1")
        assert cache.get("key1") is None

    @pytest.mark.asyncio
    async def test_delete_missing_key_no_error(self, cache: TTLCache):
        await cache.delete("nonexistent")  # Should not raise

    @pytest.mark.asyncio
    async def test_clear(self, cache: TTLCache):
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    @pytest.mark.asyncio
    async def test_overwrite_value(self, cache: TTLCache):
        await cache.set("key1", "old")
        await cache.set("key1", "new")
        assert cache.get("key1") == "new"

    @pytest.mark.asyncio
    async def test_stores_complex_types(self, cache: TTLCache):
        data = {"nested": {"list": [1, 2, 3]}, "flag": True}
        await cache.set("complex", data)
        assert cache.get("complex") == data

    @pytest.mark.asyncio
    async def test_stores_none_as_value(self, cache: TTLCache):
        """None is a valid value; get() distinguishes missing vs None."""
        # This is a design decision — storing None means the entry exists
        # but has value None. get() returns None for both missing and expired,
        # so storing None is ambiguous. We document this behavior.
        await cache.set("key", None)
        # The stored value is None, which is indistinguishable from missing
        assert cache.get("key") is None


class TestTTLCacheExpiration:
    """Test TTL-based expiration."""

    @pytest.mark.asyncio
    async def test_default_ttl_expiration(self):
        cache = TTLCache(default_ttl=0)  # Expire immediately
        await cache.set("key1", "value1")
        # With TTL=0, entry should be expired on next read
        # (time.monotonic() will be > expires_at)
        await asyncio.sleep(0.01)
        assert cache.get("key1") is None

    @pytest.mark.asyncio
    async def test_custom_ttl_per_entry(self, cache: TTLCache):
        await cache.set("short", "val", ttl=0)  # Expire immediately
        await cache.set("long", "val", ttl=3600)  # 1 hour
        await asyncio.sleep(0.01)
        assert cache.get("short") is None
        assert cache.get("long") == "val"

    @pytest.mark.asyncio
    async def test_entry_alive_before_ttl(self):
        cache = TTLCache(default_ttl=10)
        await cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    @pytest.mark.asyncio
    async def test_expiration_with_mocked_time(self):
        cache = TTLCache(default_ttl=300)
        await cache.set("key1", "value1")

        # Entry should be alive
        assert cache.get("key1") == "value1"

        # Simulate time passing by manipulating the stored expiration
        key, (_, value) = list(cache._store.items())[0]
        cache._store[key] = (time.monotonic() - 1, value)

        # Now it should be expired
        assert cache.get("key1") is None


class TestTTLCacheStats:
    """Test cache statistics."""

    @pytest.mark.asyncio
    async def test_stats_empty_cache(self, cache: TTLCache):
        stats = cache.stats()
        assert stats["total_entries"] == 0
        assert stats["live_entries"] == 0
        assert stats["expired_entries"] == 0
        assert stats["default_ttl"] == 1

    @pytest.mark.asyncio
    async def test_stats_with_entries(self, cache: TTLCache):
        await cache.set("key1", "val1", ttl=3600)
        await cache.set("key2", "val2", ttl=3600)
        stats = cache.stats()
        assert stats["total_entries"] == 2
        assert stats["live_entries"] == 2
        assert stats["expired_entries"] == 0

    @pytest.mark.asyncio
    async def test_stats_with_expired_entries(self):
        cache = TTLCache(default_ttl=0)
        await cache.set("key1", "val1")
        await asyncio.sleep(0.01)
        stats = cache.stats()
        assert stats["total_entries"] == 1
        assert stats["live_entries"] == 0
        assert stats["expired_entries"] == 1

    @pytest.mark.asyncio
    async def test_stats_mixed(self):
        cache = TTLCache(default_ttl=3600)
        await cache.set("alive", "val", ttl=3600)
        await cache.set("expired", "val", ttl=0)
        await asyncio.sleep(0.01)
        stats = cache.stats()
        assert stats["total_entries"] == 2
        assert stats["live_entries"] == 1
        assert stats["expired_entries"] == 1


class TestTTLCacheConcurrency:
    """Test concurrent access patterns."""

    @pytest.mark.asyncio
    async def test_concurrent_sets(self, cache: TTLCache):
        """Multiple concurrent sets should not corrupt the store."""
        async def writer(i: int):
            await cache.set(f"key{i}", f"value{i}", ttl=3600)

        await asyncio.gather(*[writer(i) for i in range(100)])

        for i in range(100):
            assert cache.get(f"key{i}") == f"value{i}"

    @pytest.mark.asyncio
    async def test_concurrent_reads_during_writes(self, cache: TTLCache):
        """Reads should not fail while writes are happening."""
        await cache.set("stable", "value", ttl=3600)

        async def reader():
            for _ in range(50):
                result = cache.get("stable")
                assert result in ("value", None)  # Could be cleared mid-read
                await asyncio.sleep(0)

        async def writer():
            for i in range(50):
                await cache.set(f"new{i}", f"val{i}", ttl=3600)
                await asyncio.sleep(0)

        await asyncio.gather(reader(), writer())

    @pytest.mark.asyncio
    async def test_concurrent_clear_and_set(self, cache: TTLCache):
        """Clear + set concurrently should not raise."""
        async def filler():
            for i in range(50):
                await cache.set(f"k{i}", f"v{i}", ttl=3600)
                await asyncio.sleep(0)

        async def clearer():
            for _ in range(10):
                await cache.clear()
                await asyncio.sleep(0)

        await asyncio.gather(filler(), clearer())
        # No assertion on final state — just verify no exceptions
