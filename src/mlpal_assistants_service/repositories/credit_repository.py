"""Repository for user credits management.

NOTE: The user_credits table lives in the USER schema (MLPAL_USER_SCHEMA)
since credits are universal across all MLpal services.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mlpal_assistants_service.db.models import CreditType, UserCredits
from mlpal_assistants_service.repositories.base import BaseRepository


def utcnow() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


class CreditRepository(BaseRepository[UserCredits]):
    """
    Repository for UserCredits data access.

    Provides methods for:
    - Fetching available credits
    - Consuming credits (FIFO - oldest first)
    - Adding new credits
    - Checking balances
    """

    model = UserCredits

    async def get_available_credits(
        self,
        user_id: int,
    ) -> list[UserCredits]:
        """
        Get all active, non-expired credit pools with remaining balance.

        Returns credits ordered by:
        1. Expiring soonest (to use them before they expire)
        2. Oldest first (FIFO)

        Args:
            user_id: User ID (integer, references users.id)

        Returns:
            List of available credit pools
        """
        now = utcnow()

        query = (
            select(UserCredits)
            .where(
                UserCredits.user_id == user_id,
                UserCredits.is_active == True,  # noqa: E712
                UserCredits.total_cu > UserCredits.used_cu,  # Has remaining balance
                or_(
                    UserCredits.expires_at.is_(None),  # Never expires
                    UserCredits.expires_at > now,      # Not yet expired
                ),
            )
            .order_by(
                # Expiring credits first (NULL = never expires, so last)
                UserCredits.expires_at.asc().nulls_last(),
                # Then oldest first (FIFO)
                UserCredits.created_at.asc(),
            )
        )

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_total_available(self, user_id: int) -> Decimal:
        """
        Get total available credit balance across all pools.

        Args:
            user_id: User ID

        Returns:
            Total remaining CU
        """
        now = utcnow()

        query = select(
            func.coalesce(
                func.sum(UserCredits.total_cu - UserCredits.used_cu),
                Decimal("0")
            )
        ).where(
            UserCredits.user_id == user_id,
            UserCredits.is_active == True,  # noqa: E712
            UserCredits.total_cu > UserCredits.used_cu,
            or_(
                UserCredits.expires_at.is_(None),
                UserCredits.expires_at > now,
            ),
        )

        result = await self.session.execute(query)
        return Decimal(str(result.scalar_one()))

    async def get_total_used(self, user_id: int) -> Decimal:
        """
        Get total credits used across all pools.

        Args:
            user_id: User ID

        Returns:
            Total used CU
        """
        query = select(
            func.coalesce(func.sum(UserCredits.used_cu), Decimal("0"))
        ).where(
            UserCredits.user_id == user_id,
        )

        result = await self.session.execute(query)
        return Decimal(str(result.scalar_one()))

    async def consume_credits(
        self,
        user_id: int,
        amount: Decimal,
    ) -> Decimal:
        """
        Consume credits from available pools (FIFO with expiring first).

        This method:
        1. Gets available credit pools ordered by expiration/age
        2. Consumes from each pool until amount is fulfilled
        3. Returns actual amount consumed

        Args:
            user_id: User ID
            amount: Amount of CU to consume

        Returns:
            Actual amount consumed (may be less if insufficient credits)
        """
        if amount <= Decimal("0"):
            return Decimal("0")

        pools = await self.get_available_credits(user_id)
        remaining = amount
        total_consumed = Decimal("0")

        for pool in pools:
            if remaining <= Decimal("0"):
                break

            available = pool.total_cu - pool.used_cu
            to_consume = min(remaining, available)

            # Update the pool
            await self.session.execute(
                update(UserCredits)
                .where(UserCredits.id == pool.id)
                .values(
                    used_cu=UserCredits.used_cu + to_consume,
                    updated_at=utcnow(),
                )
            )

            total_consumed += to_consume
            remaining -= to_consume

        return total_consumed

    async def add_credits(
        self,
        user_id: int,
        credit_type: CreditType,
        amount_cu: Decimal,
        expires_at: datetime | None = None,
        reference: str | None = None,
        description: str | None = None,
    ) -> UserCredits:
        """
        Add a new credit pool for a user.

        Args:
            user_id: User ID
            credit_type: Type of credit
            amount_cu: Amount of CU to add
            expires_at: Optional expiration date
            reference: Optional external reference
            description: Optional description

        Returns:
            Created UserCredits record
        """
        credits = UserCredits(
            user_id=user_id,
            credit_type=credit_type.value,
            total_cu=amount_cu,
            used_cu=Decimal("0"),
            expires_at=expires_at,
            reference=reference,
            description=description,
        )

        self.session.add(credits)
        await self.session.flush()
        await self.session.refresh(credits)

        return credits

    async def has_free_credits(self, user_id: int) -> bool:
        """
        Check if user already has free credits allocated.

        Args:
            user_id: User ID

        Returns:
            True if user has free credits record
        """
        query = select(func.count(UserCredits.id)).where(
            UserCredits.user_id == user_id,
            UserCredits.credit_type == CreditType.FREE.value,
        )

        result = await self.session.execute(query)
        count = result.scalar_one()
        return count > 0

    async def get_credits_by_type(
        self,
        user_id: int,
        credit_type: CreditType,
    ) -> list[UserCredits]:
        """
        Get all credits of a specific type for a user.

        Args:
            user_id: User ID
            credit_type: Type of credit

        Returns:
            List of matching credit records
        """
        query = (
            select(UserCredits)
            .where(
                UserCredits.user_id == user_id,
                UserCredits.credit_type == credit_type.value,
            )
            .order_by(UserCredits.created_at.desc())
        )

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_credits_summary(self, user_id: int) -> dict:
        """
        Get a summary of all credits for a user.

        Returns:
            Dict with total, used, available, and breakdown by type
        """
        now = utcnow()

        # Get all credits for user
        query = select(UserCredits).where(UserCredits.user_id == user_id)
        result = await self.session.execute(query)
        all_credits = list(result.scalars().all())

        # Calculate totals
        total_allocated = Decimal("0")
        total_used = Decimal("0")
        by_type: dict[str, dict] = {}

        for credit in all_credits:
            total_allocated += credit.total_cu
            total_used += credit.used_cu

            credit_type = credit.credit_type
            if credit_type not in by_type:
                by_type[credit_type] = {
                    "allocated": Decimal("0"),
                    "used": Decimal("0"),
                    "available": Decimal("0"),
                }

            by_type[credit_type]["allocated"] += credit.total_cu
            by_type[credit_type]["used"] += credit.used_cu

            # Only count as available if active and not expired
            if credit.is_active and (credit.expires_at is None or credit.expires_at > now):
                remaining = credit.total_cu - credit.used_cu
                if remaining > Decimal("0"):
                    by_type[credit_type]["available"] += remaining

        # Get total available (from valid pools only)
        total_available = await self.get_total_available(user_id)

        return {
            "total_allocated": float(total_allocated),
            "total_used": float(total_used),
            "total_available": float(total_available),
            "by_type": {
                k: {
                    "allocated": float(v["allocated"]),
                    "used": float(v["used"]),
                    "available": float(v["available"]),
                }
                for k, v in by_type.items()
            },
        }
