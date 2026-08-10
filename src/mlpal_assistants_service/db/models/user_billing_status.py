"""User billing status model.

NOTE: The user_billing_status table lives in the USER schema (MLPAL_USER_SCHEMA)
since billing status is universal across all MLpal services (assistants, agents, CDE).

This table is:
- OWNED by the payment service (writes status changes)
- READ by all API services (to check if user can make requests)
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from mlpal_assistants_service.core.config import get_settings
from mlpal_assistants_service.db.models.base import Base


class BillingStatus(str, Enum):
    """User billing status enum."""

    ACTIVE = "active"  # User can use APIs
    SUSPENDED = "suspended"  # Temporarily blocked (e.g., payment pending)
    BLOCKED = "blocked"  # Permanently blocked (e.g., TOS violation)


class UserBillingStatus(Base):
    """
    User billing status for API access control.

    This is the single source of truth for whether a user can make API requests.
    The payment service updates this based on billing events.

    Attributes:
        user_id: Foreign key to users table
        status: Current billing status (active, suspended, blocked)
        spending_limit_cu: Optional spending limit in compute units (NULL = unlimited)
        current_period_cu: CU used in current billing period (reset monthly by payment service)
        suspended_at: When the user was suspended
        suspended_reason: Why the user was suspended
        created_at: Record creation timestamp
        updated_at: Last update timestamp
    """

    __tablename__ = "user_billing_status"

    @declared_attr
    def __table_args__(cls):
        user_schema = get_settings().user_schema
        return (
            Index("ix_user_billing_status_status", "status"),
            {"schema": user_schema},
        )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, nullable=False, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=BillingStatus.ACTIVE.value
    )
    spending_limit_cu: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True, default=None
    )
    current_period_cu: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal("0")
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def is_active(self) -> bool:
        """Check if user can make API requests."""
        return self.status == BillingStatus.ACTIVE.value

    def is_within_limit(self, additional_cu: Decimal = Decimal("0")) -> bool:
        """Check if user is within spending limit."""
        if self.spending_limit_cu is None:
            return True  # No limit set
        return (self.current_period_cu + additional_cu) <= self.spending_limit_cu
