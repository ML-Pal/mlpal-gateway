"""Add wallet debit state to usage logs.

Revision ID: 20260406_0105
Revises: 6e7f8g9h0i1j
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260406_0105"
down_revision: str | Sequence[str] | None = "6e7f8g9h0i1j"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "usage_logs",
        sa.Column(
            "wallet_debit_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_applicable",
        ),
        schema="assistants",
    )
    op.add_column(
        "usage_logs",
        sa.Column(
            "wallet_debit_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        schema="assistants",
    )
    op.add_column(
        "usage_logs",
        sa.Column("wallet_debit_error", sa.Text(), nullable=True),
        schema="assistants",
    )
    op.add_column(
        "usage_logs",
        sa.Column("wallet_debited_at", sa.DateTime(timezone=True), nullable=True),
        schema="assistants",
    )
    op.create_index(
        "idx_usage_wallet_debit_status",
        "usage_logs",
        ["wallet_debit_status", "created_at"],
        unique=False,
        schema="assistants",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_usage_wallet_debit_status",
        table_name="usage_logs",
        schema="assistants",
    )
    op.drop_column("usage_logs", "wallet_debited_at", schema="assistants")
    op.drop_column("usage_logs", "wallet_debit_error", schema="assistants")
    op.drop_column("usage_logs", "wallet_debit_attempts", schema="assistants")
    op.drop_column("usage_logs", "wallet_debit_status", schema="assistants")
