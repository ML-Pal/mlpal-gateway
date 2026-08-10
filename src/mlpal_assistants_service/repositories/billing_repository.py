"""Repository for user billing status management.

NOTE: The user_billing_status table lives in the USER schema (MLPAL_USER_SCHEMA)
since billing status is universal across all MLpal services.

This repository is READ-ONLY for API services. The payment service owns writes.
"""

import json
import logging
from decimal import Decimal
from datetime import datetime, timezone

import httpx
import redis.asyncio as redis
from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mlpal_assistants_service.core.config import get_settings
from mlpal_assistants_service.db.models import BillingStatus, UserBillingStatus
from mlpal_assistants_service.repositories.base import BaseRepository

# Relocated to the billing seam so OSS services can import it without dragging
# in this managed wallet module; re-exported here for backward compatibility.
from mlpal_assistants_service.seams.billing import is_insufficient_wallet_error  # noqa: F401

logger = logging.getLogger(__name__)

BILLING_CACHE_TTL = 60  # seconds
WALLET_CONFIG_CACHE_KEY = "wallet:config"


def _service_auth_headers(settings) -> dict[str, str]:
    """Build outbound auth headers for backend internal calls.

    Sends BOTH:
      * Authorization: Bearer mlpal_svc_*       (MSI, preferred)
      * X-Internal-Service-Key: <legacy>        (legacy, deprecated)

    Backend's receiver accepts either during the MSI parallel-acceptance
    window. We send both so the call works whether or not backend's
    receiver has been migrated yet. Drop the X-Internal-Service-Key
    once backend is fully on MSI and we've waited the cutover period.
    """
    headers: dict[str, str] = {}
    if settings.service_identity_token:
        headers["Authorization"] = f"Bearer {settings.service_identity_token}"
    if settings.internal_service_api_key:
        headers["X-Internal-Service-Key"] = settings.internal_service_api_key
    return headers


def utcnow() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


class BillingRepository(BaseRepository[UserBillingStatus]):
    """
    Repository for UserBillingStatus data access.

    Provides methods for:
    - Checking if a user is active (can make API requests)
    - Getting billing status
    - Creating default status for new users
    - Updating current period usage

    Note: Status changes (suspend/block) are handled by the payment service.
    This service only reads status and updates usage counters.
    """

    model = UserBillingStatus

    def __init__(self, session: AsyncSession, redis_client: redis.Redis | None = None) -> None:
        super().__init__(session)
        self._redis = redis_client
        self._settings = get_settings()

    async def is_wallet_gating_enabled(self) -> bool:
        """Return whether walletGatingEnabled is currently on in the backend
        platform config. Used by serving paths to skip wallet debits when
        gating is off — preventing double deduction against the CU v3
        wallet-minus-usage display in the frontend.
        """
        config = await self._get_wallet_rollout_config()
        return bool(config.get("wallet_gating_enabled", False))

    async def is_wallet_debit_active(self) -> bool:
        """Whether a wallet debit should actually be performed.

        Both switches must be on: the service-level ``wallet_debit_enabled``
        kill switch (temporary, for the wallet rework) AND the backend
        ``walletGatingEnabled`` rollout flag. When either is off, callers skip
        the debit and record usage as 'not_applicable' — usage is still logged.
        The kill switch is checked first so a disabled debit needs no backend
        round-trip.
        """
        if not self._settings.wallet_debit_enabled:
            return False
        return await self.is_wallet_gating_enabled()

    async def _cache_get(self, key: str) -> str | None:
        """Read from Redis, treating any Redis error as a cache miss.

        Redis fronts an HTTP source of truth here, so a Redis outage must
        degrade to the HTTP path — never propagate and fail the billing gate.
        """
        if not self._redis:
            return None
        try:
            return await self._redis.get(key)
        except RedisError as e:
            logger.warning("billing_cache_degraded: get failed", extra={"key": key, "error": str(e)})
            return None

    async def _cache_setex(self, key: str, ttl: int, value: str) -> None:
        """Best-effort cache write; swallow Redis errors."""
        if not self._redis:
            return
        try:
            await self._redis.setex(key, ttl, value)
        except RedisError as e:
            logger.warning("billing_cache_degraded: setex failed", extra={"key": key, "error": str(e)})

    async def _get_wallet_rollout_config(self) -> dict[str, bool]:
        cached = await self._cache_get(WALLET_CONFIG_CACHE_KEY)
        if cached:
            return json.loads(cached)

        headers = _service_auth_headers(self._settings)

        async with httpx.AsyncClient(
            base_url=self._settings.backend_base_url,
            timeout=httpx.Timeout(self._settings.wallet_timeout_seconds),
            headers=headers,
        ) as client:
            response = await client.get("/api/v1/internal/config/platform")
            response.raise_for_status()
            payload = response.json().get("data", {})

        config = {"wallet_gating_enabled": bool(payload.get("walletGatingEnabled", False))}
        await self._cache_setex(
            WALLET_CONFIG_CACHE_KEY,
            self._settings.wallet_cache_ttl_seconds,
            json.dumps(config),
        )
        return config

    async def _get_wallet_gate_snapshot(self, user_id: int) -> dict[str, str | bool]:
        config = await self._get_wallet_rollout_config()
        if not config.get("wallet_gating_enabled", False):
            return {
                "wallet_gating_enabled": False,
                "wallet_access_status": "compatibility",
                "wallet_balance_cu": "0",
            }

        cache_key = f"wallet:{user_id}"
        cached = await self._cache_get(cache_key)
        if cached:
            return json.loads(cached)

        headers = _service_auth_headers(self._settings)

        async with httpx.AsyncClient(
            base_url=self._settings.payments_base_url,
            timeout=httpx.Timeout(self._settings.wallet_timeout_seconds),
            headers=headers,
        ) as client:
            response = await client.get(f"/api/v1/internal/wallet/balance/{user_id}")
            response.raise_for_status()
            payload = response.json().get("data", {})

        balance = Decimal(str(payload.get("balance", "0")))
        snapshot = {
            "wallet_gating_enabled": True,
            "wallet_access_status": ("allowed" if balance > 0 else "insufficient_balance"),
            "wallet_balance_cu": str(balance),
        }
        await self._cache_setex(
            cache_key,
            self._settings.wallet_cache_ttl_seconds,
            json.dumps(snapshot),
        )
        return snapshot

    async def can_make_request_cached(
        self,
        user_id: int,
        estimated_cu: Decimal = Decimal("0"),
    ) -> tuple[bool, str | None, bool]:
        """
        Check if a user can make an API request, with Redis caching.

        Returns (allowed, reason, billing_existed) where billing_existed=False
        means ensure_billing_status should be called in the background.
        """
        wallet_gate = await self._get_wallet_gate_snapshot(user_id)
        if wallet_gate.get("wallet_gating_enabled", False):
            if wallet_gate.get("wallet_access_status") == "allowed":
                return True, None, True
            if wallet_gate.get("wallet_access_status") == "insufficient_balance":
                return False, "Wallet balance is required", True

        cache_key = f"billing:{user_id}"
        cached = await self._cache_get(cache_key)
        if cached:
            data = json.loads(cached)
            status_val = data["status"]
            if status_val == BillingStatus.SUSPENDED.value:
                return False, data.get("suspended_reason") or "Account suspended", True
            if status_val == BillingStatus.BLOCKED.value:
                return False, "Account blocked", True
            spending_limit = data.get("spending_limit_cu")
            if spending_limit is not None:
                current = Decimal(str(data["current_period_cu"]))
                if (current + estimated_cu) > Decimal(str(spending_limit)):
                    return False, "Monthly spending limit reached", True
            return True, None, True

        # Cache miss (or Redis degraded) — query DB
        billing = await self.get_by_user_id(user_id)
        if billing is None:
            # New user — cache as active, signal that ensure is needed
            await self._cache_setex(
                cache_key,
                BILLING_CACHE_TTL,
                json.dumps(
                    {
                        "status": BillingStatus.ACTIVE.value,
                        "spending_limit_cu": None,
                        "current_period_cu": "0",
                    }
                ),
            )
            return True, None, False

        # Cache the result
        await self._cache_setex(
            cache_key,
            BILLING_CACHE_TTL,
            json.dumps(
                {
                    "status": billing.status,
                    "spending_limit_cu": str(billing.spending_limit_cu)
                    if billing.spending_limit_cu is not None
                    else None,
                    "current_period_cu": str(billing.current_period_cu),
                    "suspended_reason": getattr(billing, "suspended_reason", None),
                }
            ),
        )

        # Now check from the fetched data
        if billing.status == BillingStatus.SUSPENDED.value:
            return False, getattr(billing, "suspended_reason", None) or "Account suspended", True
        if billing.status == BillingStatus.BLOCKED.value:
            return False, "Account blocked", True
        if billing.spending_limit_cu is not None:
            if (billing.current_period_cu + estimated_cu) > billing.spending_limit_cu:
                return False, "Monthly spending limit reached", True
        return True, None, True

    async def increment_usage_cached(
        self,
        user_id: int,
        compute_units: Decimal,
    ) -> None:
        """Increment usage in both Redis cache and DB."""
        # Update Redis cache (best-effort; DB below is the source of truth)
        cache_key = f"billing:{user_id}"
        cached = await self._cache_get(cache_key)
        if cached:
            data = json.loads(cached)
            current = Decimal(str(data["current_period_cu"]))
            data["current_period_cu"] = str(current + compute_units)
            await self._cache_setex(cache_key, BILLING_CACHE_TTL, json.dumps(data))

        # Update DB
        await self.increment_usage(user_id, compute_units)

    async def get_by_user_id(self, user_id: int) -> UserBillingStatus | None:
        """
        Get billing status for a user.

        Args:
            user_id: User ID (integer, references users.id)

        Returns:
            UserBillingStatus or None if not found
        """
        query = select(UserBillingStatus).where(UserBillingStatus.user_id == user_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def is_user_active(self, user_id: int) -> bool:
        """
        Check if a user can make API requests.

        Args:
            user_id: User ID

        Returns:
            True if user is active, False otherwise
        """
        status = await self.get_by_user_id(user_id)
        if status is None:
            # No billing status = new user, allow by default
            return True
        return status.status == BillingStatus.ACTIVE.value

    async def is_within_limit(
        self,
        user_id: int,
        additional_cu: Decimal = Decimal("0"),
    ) -> bool:
        """
        Check if user is within their spending limit.

        Args:
            user_id: User ID
            additional_cu: Additional CU to check against limit

        Returns:
            True if within limit or no limit set, False otherwise
        """
        status = await self.get_by_user_id(user_id)
        if status is None:
            # No billing status = no limit
            return True
        if status.spending_limit_cu is None:
            # No limit set
            return True
        return (status.current_period_cu + additional_cu) <= status.spending_limit_cu

    async def ensure_billing_status(self, user_id: int) -> UserBillingStatus:
        """
        Ensure a billing status record exists for the user.

        Creates a new record with active status if none exists.
        This is called when a user first makes an API request.

        Args:
            user_id: User ID

        Returns:
            UserBillingStatus record
        """
        existing = await self.get_by_user_id(user_id)
        if existing:
            return existing

        # Create new billing status with defaults
        billing_status = UserBillingStatus(
            user_id=user_id,
            status=BillingStatus.ACTIVE.value,
            current_period_cu=Decimal("0"),
        )
        self.session.add(billing_status)
        await self.session.flush()
        await self.session.refresh(billing_status)
        return billing_status

    async def increment_usage(
        self,
        user_id: int,
        compute_units: Decimal,
    ) -> None:
        """
        Increment the current period usage.

        Called after each successful API request.

        Args:
            user_id: User ID
            compute_units: CU to add to usage
        """
        await self.session.execute(
            update(UserBillingStatus)
            .where(UserBillingStatus.user_id == user_id)
            .values(
                current_period_cu=UserBillingStatus.current_period_cu + compute_units,
                updated_at=utcnow(),
            )
        )

    async def can_make_request(
        self,
        user_id: int,
        estimated_cu: Decimal = Decimal("0"),
    ) -> tuple[bool, str | None]:
        """
        Check if a user can make an API request.

        Returns a tuple of (can_request, reason) where reason is None if allowed.

        Args:
            user_id: User ID
            estimated_cu: Estimated CU for the request (for limit checking)

        Returns:
            Tuple of (allowed, reason_if_blocked)
        """
        status = await self.get_by_user_id(user_id)

        if status is None:
            # New user, no billing status yet - allow and create
            return True, None

        if status.status == BillingStatus.SUSPENDED.value:
            return False, status.suspended_reason or "Account suspended"

        if status.status == BillingStatus.BLOCKED.value:
            return False, "Account blocked"

        # Check spending limit
        if status.spending_limit_cu is not None:
            if (status.current_period_cu + estimated_cu) > status.spending_limit_cu:
                return False, "Monthly spending limit reached"

        return True, None

    async def debit_wallet_usage(
        self,
        user_id: int,
        compute_units: Decimal,
        usage_ref: str,
    ) -> bool:
        headers = _service_auth_headers(self._settings)

        async with httpx.AsyncClient(
            base_url=self._settings.payments_base_url,
            timeout=httpx.Timeout(self._settings.wallet_timeout_seconds),
            headers=headers,
        ) as client:
            response = await client.post(
                "/api/v1/internal/wallet/debit",
                json={
                    "platform_user_id": user_id,
                    "amount": str(compute_units),
                    "source": "usage",
                    "source_ref": usage_ref,
                    "description": "Assistants-service usage debit",
                },
            )
            if response.status_code == 402 and self._redis:
                await self._redis.setex(
                    f"wallet:{user_id}",
                    self._settings.wallet_cache_ttl_seconds,
                    json.dumps(
                        {
                            "wallet_gating_enabled": True,
                            "wallet_access_status": "insufficient_balance",
                            "wallet_balance_cu": "0",
                        }
                    ),
                )
            response.raise_for_status()

        if self._redis:
            await self._redis.delete(f"wallet:{user_id}")
        return True
