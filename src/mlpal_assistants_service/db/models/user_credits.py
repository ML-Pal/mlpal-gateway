"""User credits model for pay-as-you-go billing.

The credits system supports:
- Free credits: Initial allocation for new users (e.g., 50 CU for builders)
- Purchased credits: Pay-as-you-go top-ups
- Promotional credits: Time-limited bonus credits

Each credit record tracks:
- Total allocated CU
- Used CU
- Optional expiration date

NOTE: This table lives in the USER schema (MLPAL_USER_SCHEMA) since credits
are universal across all MLpal services (agents, CDE, assistants).
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, declared_attr

from mlpal_assistants_service.core.config import get_settings
from mlpal_assistants_service.db.models.base import Base


class CreditType(str, Enum):
    """Types of compute unit credits."""

    FREE = "free"              # Initial free allocation
    PURCHASED = "purchased"    # Pay-as-you-go purchased credits
    PROMOTIONAL = "promotional"  # Time-limited bonus credits
    REFERRAL = "referral"      # Credits from referral program


# Default free credits by user role
FREE_CREDITS_BY_ROLE: dict[str, Decimal] = {
    "builder": Decimal("50.0"),   # 50 CU for builders
    "user": Decimal("10.0"),      # 10 CU for regular users
    "admin": Decimal("100.0"),    # 100 CU for admins
}


class UserCredits(Base):
    """
    Track compute unit credits for users.

    This table lives in the USER schema (same as users table) since credits
    are universal across all MLpal services.

    Supports multiple credit pools per user:
    - Free credits (never expire, one-time allocation)
    - Purchased credits (never expire, can be added multiple times)
    - Promotional credits (may expire)

    Usage flow:
    1. User signs up -> Gets free credits based on role
    2. User purchases more credits -> New "purchased" record added
    3. On each request -> Credits consumed from oldest non-expired pool first
    4. When credits depleted -> Request rejected with QuotaExceededError

    Example:
        # Check available credits
        available = await credit_service.get_available_credits(user_id)

        # Consume credits
        await credit_service.consume_credits(user_id, Decimal("0.05"))

        # Add purchased credits
        await credit_service.add_credits(
            user_id=user_id,
            credit_type=CreditType.PURCHASED,
            amount_cu=Decimal("100.0"),
            reference="stripe_payment_xyz",
        )
    """

    __tablename__ = "user_credits"

    @declared_attr
    def __table_args__(cls):
        user_schema = get_settings().user_schema
        return (
            Index(
                "ix_user_credits_active_available",
                "user_id",
                "is_active",
                "expires_at",
            ),
            Index(
                "ix_user_credits_user_type",
                "user_id",
                "credit_type",
            ),
            {"schema": user_schema},
        )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Reference to users.id in the user schema
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # Credit type and amounts
    credit_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=CreditType.FREE.value,
    )
    total_cu: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
        default=Decimal("0"),
        comment="Total CU allocated",
    )
    used_cu: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
        default=Decimal("0"),
        comment="CU consumed from this pool",
    )

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Optional expiration (NULL = never expires)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When these credits expire (NULL = never)",
    )

    # Reference for tracking (e.g., stripe payment ID, promo code)
    reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="External reference (payment ID, promo code, etc.)",
    )

    # Description for display
    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Human-readable description",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @property
    def remaining_cu(self) -> Decimal:
        """Calculate remaining credits in this pool."""
        return self.total_cu - self.used_cu

    @property
    def is_expired(self) -> bool:
        """Check if credits have expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at.replace(tzinfo=None)

    @property
    def is_available(self) -> bool:
        """Check if credits are available for use."""
        return (
            self.is_active
            and not self.is_expired
            and self.remaining_cu > Decimal("0")
        )

    def consume(self, amount: Decimal) -> Decimal:
        """
        Consume credits from this pool.

        Args:
            amount: Amount of CU to consume

        Returns:
            Actual amount consumed (may be less if pool depleted)
        """
        available = self.remaining_cu
        to_consume = min(amount, available)
        self.used_cu += to_consume
        return to_consume

    def __repr__(self) -> str:
        return (
            f"<UserCredits(id={self.id}, user_id={self.user_id}, "
            f"type={self.credit_type}, remaining={self.remaining_cu})>"
        )
