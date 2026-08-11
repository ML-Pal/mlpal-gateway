"""Partial unique index enforcing one platform-fee row per (user, month).

The fee row's trace_id is deterministic (`fee_{user}_{YYYYMM}`), so uniqueness
on trace_id scoped to operation='platform_fee' makes the charge idempotent
under concurrency (check-then-insert races lose on this constraint).

Revision ID: 20260811_2200
Revises: 20260811_2000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260811_2200"
down_revision: str | Sequence[str] | None = "20260811_2000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_usage_platform_fee_unique
        ON assistants.usage_logs (trace_id)
        WHERE operation = 'platform_fee'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS assistants.idx_usage_platform_fee_unique")
