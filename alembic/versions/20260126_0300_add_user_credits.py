"""add_user_credits

Revision ID: 2a3b4c5d6e7f
Revises: 41438244c0af
Create Date: 2026-01-26 03:00:00.000000

Adds user_credits table for pay-as-you-go billing with free credits.
This table is created in the USER schema (MLPAL_USER_SCHEMA) since credits
are universal across all MLpal services (agents, CDE, assistants).

Credit types:
- free: Initial allocation for new users (e.g., 50 CU for builders)
- purchased: Pay-as-you-go top-ups
- promotional: Time-limited bonus credits
- referral: Credits from referral program
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from mlpal_assistants_service.core.config import get_settings

# revision identifiers, used by Alembic.
revision: str = '2a3b4c5d6e7f'
down_revision: str | None = '41438244c0af'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def get_user_schema() -> str:
    """Get user schema from settings."""
    return get_settings().user_schema


def upgrade() -> None:
    user_schema = get_user_schema()

    # Create schema if it doesn't exist
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {user_schema}")

    # Create user_credits table in the USER schema (where users table lives)
    op.create_table('user_credits',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        # user_id references users.id in the same schema
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('credit_type', sa.String(length=20), nullable=False, server_default='free',
                  comment="Credit type: free, purchased, promotional, referral"),
        sa.Column('total_cu', sa.Numeric(precision=12, scale=6), nullable=False, server_default='0',
                  comment="Total CU allocated"),
        sa.Column('used_cu', sa.Numeric(precision=12, scale=6), nullable=False, server_default='0',
                  comment="CU consumed from this pool"),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True,
                  comment="When these credits expire (NULL = never)"),
        sa.Column('reference', sa.String(length=255), nullable=True,
                  comment="External reference (payment ID, promo code, etc.)"),
        sa.Column('description', sa.String(length=500), nullable=True,
                  comment="Human-readable description"),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], [f'{user_schema}.users.id'], ondelete='CASCADE'),
        schema=user_schema
    )

    # Index for finding active, non-expired credits
    op.create_index('ix_user_credits_active_available', 'user_credits',
                    ['user_id', 'is_active', 'expires_at'], schema=user_schema)

    # Index for credit type queries
    op.create_index('ix_user_credits_user_type', 'user_credits',
                    ['user_id', 'credit_type'], schema=user_schema)

    # Index for user lookups
    op.create_index('ix_user_credits_user_id', 'user_credits',
                    ['user_id'], schema=user_schema)


def downgrade() -> None:
    user_schema = get_user_schema()

    op.drop_index('ix_user_credits_user_id', table_name='user_credits', schema=user_schema)
    op.drop_index('ix_user_credits_user_type', table_name='user_credits', schema=user_schema)
    op.drop_index('ix_user_credits_active_available', table_name='user_credits', schema=user_schema)
    op.drop_table('user_credits', schema=user_schema)
