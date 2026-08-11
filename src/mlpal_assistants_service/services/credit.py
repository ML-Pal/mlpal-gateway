"""Credit service for managing user compute unit credits.

The CreditService provides:
- Credit balance checking
- Credit consumption (with FIFO ordering)
- Free credit allocation for new users
- Credit purchase recording
"""

import logging
from decimal import Decimal

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mlpal_assistants_service.core.config import get_settings
from mlpal_assistants_service.core.exceptions import QuotaExceededError
from mlpal_assistants_service.db.models import FREE_CREDITS_BY_ROLE, CreditType, UserCredits
from mlpal_assistants_service.repositories import CreditRepository

logger = logging.getLogger(__name__)


class CreditService:
    """
    Service for managing user compute unit credits.

    Handles:
    - Checking available credits
    - Consuming credits for requests
    - Allocating free credits to new users
    - Adding purchased/promotional credits

    Usage:
        service = CreditService(session, redis_client)

        # Check if user has enough credits
        has_credits = await service.check_credits(user_id=1, required_cu=Decimal("0.5"))

        # Consume credits after request
        await service.consume_credits(user_id=1, amount_cu=Decimal("0.5"))

        # Get credit summary
        summary = await service.get_credits_summary(user_id=1)
    """

    CACHE_TTL = 60  # 1 minute cache for credit balance
    CACHE_PREFIX = "credits:"

    def __init__(
        self,
        session: AsyncSession,
        redis_client: redis.Redis | None = None,
    ) -> None:
        self.session = session
        self.redis = redis_client
        self.settings = get_settings()
        self._repo = CreditRepository(session)

    async def check_credits(
        self,
        user_id: int,
        required_cu: Decimal,
    ) -> bool:
        """
        Check if user has sufficient credits for a request.

        Args:
            user_id: User ID
            required_cu: Required compute units

        Returns:
            True if user has enough credits
        """
        available = await self.get_available_credits(user_id)
        return available >= required_cu

    async def get_available_credits(self, user_id: int) -> Decimal:
        """
        Get total available credits for a user.

        Uses Redis cache for fast lookups.

        Args:
            user_id: User ID

        Returns:
            Available CU balance
        """
        # Check cache first
        if self.redis:
            cache_key = f"{self.CACHE_PREFIX}{user_id}:available"
            cached = await self.redis.get(cache_key)
            if cached:
                return Decimal(cached)

        # Get from database
        available = await self._repo.get_total_available(user_id)

        # Cache it
        if self.redis:
            await self.redis.setex(
                f"{self.CACHE_PREFIX}{user_id}:available",
                self.CACHE_TTL,
                str(available),
            )

        return available

    async def consume_credits(
        self,
        user_id: int,
        amount_cu: Decimal,
        allow_partial: bool = False,
    ) -> Decimal:
        """
        Consume credits from user's pools.

        Credits are consumed in order:
        1. Expiring soonest (to use before they expire)
        2. Oldest first (FIFO)

        Args:
            user_id: User ID
            amount_cu: Amount of CU to consume
            allow_partial: If True, consume what's available even if less than requested

        Returns:
            Actual amount consumed

        Raises:
            QuotaExceededError: If insufficient credits and allow_partial=False
        """
        if amount_cu <= Decimal("0"):
            return Decimal("0")

        # Check available first
        available = await self.get_available_credits(user_id)

        if available < amount_cu and not allow_partial:
            raise QuotaExceededError(
                message="Insufficient compute unit credits",
                current_usage=float(await self._repo.get_total_used(user_id)),
                limit=float(available),
            )

        # Consume credits
        consumed = await self._repo.consume_credits(user_id, amount_cu)

        # Invalidate cache
        await self._invalidate_cache(user_id)

        return consumed

    async def ensure_free_credits(self, user_id: int, role: str = "user") -> bool:
        """
        Ensure user has their initial free credits allocated.

        Called when user first makes an API request. If they don't have
        free credits yet, allocate based on their role.

        Args:
            user_id: User ID
            role: User role (builder, user, admin)

        Returns:
            True if credits were allocated, False if already had them
        """
        # Check if already has free credits
        has_free = await self._repo.has_free_credits(user_id)
        if has_free:
            return False

        # Get free credit amount for role
        amount = FREE_CREDITS_BY_ROLE.get(role, FREE_CREDITS_BY_ROLE["user"])

        # Allocate free credits
        await self._repo.add_credits(
            user_id=user_id,
            credit_type=CreditType.FREE,
            amount_cu=amount,
            description=f"Initial free credits for {role} role",
        )

        logger.info(f"Allocated {amount} free CU to user {user_id} (role={role})")

        # Invalidate cache
        await self._invalidate_cache(user_id)

        return True

    async def add_purchased_credits(
        self,
        user_id: int,
        amount_cu: Decimal,
        reference: str,
        description: str | None = None,
    ) -> UserCredits:
        """
        Add purchased credits to user's account.

        Args:
            user_id: User ID
            amount_cu: Amount of CU purchased
            reference: Payment reference (e.g., Stripe payment ID)
            description: Optional description

        Returns:
            Created UserCredits record
        """
        credits = await self._repo.add_credits(
            user_id=user_id,
            credit_type=CreditType.PURCHASED,
            amount_cu=amount_cu,
            reference=reference,
            description=description or f"Purchased {amount_cu} CU",
        )

        logger.info(f"Added {amount_cu} purchased CU to user {user_id} (ref={reference})")

        # Invalidate cache
        await self._invalidate_cache(user_id)

        return credits

    async def add_promotional_credits(
        self,
        user_id: int,
        amount_cu: Decimal,
        expires_at,
        reference: str | None = None,
        description: str | None = None,
    ) -> UserCredits:
        """
        Add promotional credits with expiration.

        Args:
            user_id: User ID
            amount_cu: Amount of promotional CU
            expires_at: Expiration datetime
            reference: Optional reference (promo code, etc.)
            description: Optional description

        Returns:
            Created UserCredits record
        """
        credits = await self._repo.add_credits(
            user_id=user_id,
            credit_type=CreditType.PROMOTIONAL,
            amount_cu=amount_cu,
            expires_at=expires_at,
            reference=reference,
            description=description or f"Promotional {amount_cu} CU",
        )

        logger.info(f"Added {amount_cu} promotional CU to user {user_id}")

        # Invalidate cache
        await self._invalidate_cache(user_id)

        return credits

    async def get_credits_summary(self, user_id: int) -> dict:
        """
        Get detailed credit summary for a user.

        Returns:
            Dict with total_allocated, total_used, total_available, and breakdown by type
        """
        return await self._repo.get_credits_summary(user_id)

    async def get_user_role(self, user_id: int) -> str:
        """
        Get user's role from the users table.

        Args:
            user_id: User ID

        Returns:
            User role (builder, user, admin, etc.)
        """
        user_schema = self.settings.user_schema
        query = text(f"SELECT role FROM {user_schema}.users WHERE id = :user_id")
        result = await self.session.execute(query, {"user_id": user_id})
        row = result.fetchone()
        return row[0] if row else "user"

    async def _invalidate_cache(self, user_id: int) -> None:
        """Invalidate cached credit balance for user."""
        if self.redis:
            await self.redis.delete(f"{self.CACHE_PREFIX}{user_id}:available")
