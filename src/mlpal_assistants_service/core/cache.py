"""In-memory TTL cache and Redis Pub/Sub cache invalidation.

TTLCache provides a per-entry TTL dict with lock-free reads for hot-path performance.
CacheInvalidator coordinates cross-instance cache invalidation via Redis Pub/Sub.
"""

import asyncio
import json
import logging
import time
from typing import Any

import redis.asyncio as redis

logger = logging.getLogger(__name__)

INVALIDATION_CHANNEL = "mlpal:cache:invalidate"


class TTLCache:
    """In-memory cache with per-entry TTL and max size limit.

    Lock-free reads for hot-path performance. Only mutations acquire the lock.
    A rare race on expiry cleanup is tolerable — worst case is serving one
    slightly-expired entry, which is fine for reference data.

    Features:
    - Per-entry TTL with automatic expiration
    - Max size limit with LRU-style eviction (oldest entries removed first)
    - Periodic cleanup of expired entries on set() operations

    Usage:
        cache = TTLCache(default_ttl=300, maxsize=10000)
        await cache.set("key", value)
        result = cache.get("key")  # lock-free read
    """

    # Clean up expired entries every N set operations
    _CLEANUP_INTERVAL = 100

    def __init__(self, default_ttl: int = 300, maxsize: int = 10000) -> None:
        self._store: dict[str, tuple[float, Any]] = {}  # key -> (expires_at, value)
        self._default_ttl = default_ttl
        self._maxsize = maxsize
        self._lock = asyncio.Lock()
        self._set_count = 0

    def get(self, key: str) -> Any | None:
        """Get a value by key. Returns None if missing or expired.

        Lock-free — plain dict lookup + timestamp check.
        """
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            # Expired — don't bother deleting here (lazy cleanup).
            # The next set() or cleanup will remove it.
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set a value with optional custom TTL."""
        expires_at = time.monotonic() + (ttl if ttl is not None else self._default_ttl)
        async with self._lock:
            # Periodic cleanup of expired entries
            self._set_count += 1
            if self._set_count >= self._CLEANUP_INTERVAL:
                self._cleanup_expired()
                self._set_count = 0

            # Evict oldest entries if at capacity (and key is new)
            if key not in self._store and len(self._store) >= self._maxsize:
                self._evict_oldest(count=max(1, self._maxsize // 10))  # Evict 10%

            self._store[key] = (expires_at, value)

    def _cleanup_expired(self) -> None:
        """Remove expired entries. Must be called with lock held."""
        now = time.monotonic()
        expired_keys = [k for k, (exp, _) in self._store.items() if exp <= now]
        for k in expired_keys:
            del self._store[k]
        if expired_keys:
            logger.debug(f"TTLCache cleanup: removed {len(expired_keys)} expired entries")

    def _evict_oldest(self, count: int = 1) -> None:
        """Evict oldest entries by expiration time. Must be called with lock held."""
        if not self._store or count <= 0:
            return
        # Sort by expiration time (oldest first) and remove
        sorted_keys = sorted(self._store.keys(), key=lambda k: self._store[k][0])
        for k in sorted_keys[:count]:
            del self._store[k]
        logger.debug(f"TTLCache eviction: removed {count} oldest entries (size: {len(self._store)})")

    async def delete(self, key: str) -> None:
        """Delete a key."""
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        """Clear all entries."""
        async with self._lock:
            self._store.clear()
            self._set_count = 0

    def stats(self) -> dict:
        """Return approximate cache statistics. No lock — counts are best-effort."""
        now = time.monotonic()
        total = len(self._store)
        live = sum(1 for exp, _ in self._store.values() if exp > now)
        return {
            "total_entries": total,
            "live_entries": live,
            "expired_entries": total - live,
            "default_ttl": self._default_ttl,
            "maxsize": self._maxsize,
        }


class CacheInvalidator:
    """Cross-instance cache invalidation via Redis Pub/Sub.

    Publisher side: call ``publish()`` to notify all instances.
    Subscriber side: call ``start_listener()`` to handle incoming invalidation messages.

    Supported targets:
        - "models"   — clear model registry caches
        - "pricing"  — clear pricing caches
        - "routing"  — clear meta-model routing caches
        - "api_keys" — clear all API key caches
        - "api_key:{key_hash}" — clear a specific API key cache entry
        - "all"      — clear everything
    """

    # Reconnect backoff bounds for the subscriber loop.
    _INITIAL_BACKOFF = 1.0
    _MAX_BACKOFF = 30.0

    def __init__(
        self,
        redis_client: redis.Redis,
        pubsub_client: redis.Redis | None = None,
    ) -> None:
        self._redis = redis_client
        # The long-lived SUBSCRIBE must draw from a connection pool that is
        # ISOLATED from the command pool, so a stuck or reconnecting subscriber
        # can never exhaust the connections that serve requests. Falls back to
        # the command client when no dedicated client is provided (tests).
        self._pubsub_client = pubsub_client or redis_client
        self._handlers: dict[str, list] = {}
        self._listener_task: asyncio.Task | None = None
        self._stopping = False

    def register(self, target: str, handler) -> None:
        """Register an async handler for a cache invalidation target.

        Args:
            target: The invalidation target (e.g. "models", "pricing").
            handler: An async callable that will be invoked on invalidation.
        """
        self._handlers.setdefault(target, []).append(handler)

    async def publish(self, target: str) -> None:
        """Publish an invalidation message to all instances.

        Args:
            target: What to invalidate (e.g. "models", "api_key:{hash}", "all").
        """
        message = json.dumps({"type": target})
        try:
            await self._redis.publish(INVALIDATION_CHANNEL, message)
            logger.info("Cache invalidation published", extra={"target": target})
        except Exception as e:
            logger.error("Failed to publish cache invalidation", extra={"target": target, "error": str(e)})

    async def _handle_message(self, target: str) -> None:
        """Dispatch invalidation to registered handlers."""
        if target == "all":
            # Fire all handlers
            for handlers in self._handlers.values():
                for handler in handlers:
                    try:
                        await handler()
                    except Exception as e:
                        logger.error("Cache invalidation handler error", extra={"error": str(e)})
            return

        # Check for exact match first (e.g. "models", "pricing")
        handlers = self._handlers.get(target, [])
        for handler in handlers:
            try:
                await handler()
            except Exception as e:
                logger.error("Cache invalidation handler error", extra={"target": target, "error": str(e)})

        # Check for prefix match (e.g. "api_key:abc123" matches "api_key" handlers)
        if ":" in target:
            prefix = target.split(":")[0]
            prefix_handlers = self._handlers.get(prefix, [])
            for handler in prefix_handlers:
                try:
                    # Pass the full target so the handler can extract the specific key
                    await handler(target)
                except TypeError:
                    # Handler doesn't accept arguments
                    await handler()
                except Exception as e:
                    logger.error("Cache invalidation handler error", extra={"target": target, "error": str(e)})

    async def start_listener(self) -> None:
        """Start the Pub/Sub listener as a background task."""
        self._listener_task = asyncio.create_task(self._listen_loop())
        logger.info("Cache invalidation listener started")

    async def _listen_loop(self) -> None:
        """Listen for invalidation messages, reconnecting with bounded backoff.

        Every iteration releases its pub/sub connection in a ``finally`` block.
        The prior implementation created a new ``pubsub()`` on each reconnect
        without closing the old one; combined with the shared command pool this
        leaked SUBSCRIBE connections until the pool was exhausted, taking down
        rate limiting, billing caches and the wallet-debit retry loop. See
        ERRORS.md (INCIDENT 2026-06-03).
        """
        backoff = self._INITIAL_BACKOFF
        while not self._stopping:
            pubsub = self._pubsub_client.pubsub()
            try:
                await pubsub.subscribe(INVALIDATION_CHANNEL)
                logger.info("Subscribed to cache invalidation channel")
                backoff = self._INITIAL_BACKOFF  # reset after a clean subscribe

                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        data = json.loads(message["data"])
                        target = data.get("type", "")
                        logger.info("Cache invalidation received", extra={"target": target})
                        await self._handle_message(target)
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning("Invalid invalidation message", extra={"error": str(e)})

            except asyncio.CancelledError:
                logger.info("Cache invalidation listener stopping")
                break
            except Exception as e:
                logger.error(
                    "Cache invalidation listener error, reconnecting",
                    extra={"error": str(e), "backoff_seconds": backoff},
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._MAX_BACKOFF)
            finally:
                # CRITICAL: always return the pub/sub connection to its pool,
                # on every exit path (normal, error, or cancellation).
                try:
                    await pubsub.aclose()
                except Exception:
                    pass

    async def stop(self) -> None:
        """Stop the Pub/Sub listener."""
        self._stopping = True
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None
