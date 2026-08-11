"""add_user_billing_status

Revision ID: 3b4c5d6e7f8a
Revises: 2a3b4c5d6e7f
Create Date: 2026-01-26 04:00:00.000000

Adds user_billing_status table for API access control.
This table is created in the USER schema (MLPAL_USER_SCHEMA) since billing
status is universal across all MLpal services (agents, CDE, assistants).

This table is:
- OWNED by the payment service (writes status changes)
- READ by all API services (to check if user can make requests)

Status values:
- active: User can use APIs
- suspended: Temporarily blocked (e.g., payment pending)
- blocked: Permanently blocked (e.g., TOS violation)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from mlpal_assistants_service.core.config import get_settings

# revision identifiers, used by Alembic.
revision: str = '3b4c5d6e7f8a'
down_revision: str | None = '2a3b4c5d6e7f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def get_user_schema() -> str:
    """Get user schema from settings."""
    return get_settings().user_schema


def upgrade() -> None:
    user_schema = get_user_schema()

    # Create user_billing_status table in the USER schema
    op.create_table('user_billing_status',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active',
                  comment="Billing status: active, suspended, blocked"),
        sa.Column('spending_limit_cu', sa.Numeric(precision=12, scale=6), nullable=True,
                  comment="Optional monthly spending limit in CU (NULL = unlimited)"),
        sa.Column('current_period_cu', sa.Numeric(precision=12, scale=6), nullable=False, server_default='0',
                  comment="CU used in current billing period"),
        sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=True,
                  comment="When the user was suspended"),
        sa.Column('suspended_reason', sa.Text(), nullable=True,
                  comment="Reason for suspension"),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], [f'{user_schema}.users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', name='uq_user_billing_status_user_id'),
        schema=user_schema
    )

    # Index for status queries
    op.create_index('ix_user_billing_status_status', 'user_billing_status',
                    ['status'], schema=user_schema)

    # Index for user lookups
    op.create_index('ix_user_billing_status_user_id', 'user_billing_status',
                    ['user_id'], schema=user_schema)


def downgrade() -> None:
    user_schema = get_user_schema()

    op.drop_index('ix_user_billing_status_user_id', table_name='user_billing_status', schema=user_schema)
    op.drop_index('ix_user_billing_status_status', table_name='user_billing_status', schema=user_schema)
    op.drop_table('user_billing_status', schema=user_schema)
