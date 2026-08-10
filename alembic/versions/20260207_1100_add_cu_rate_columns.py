"""add_cu_rate_columns

Revision ID: 6e7f8g9h0i1j
Revises: 5d6e7f8g9h0i
Create Date: 2026-02-07 11:00:00.000000

Fixes pricing calculation bug: compute_units were returning dollar amounts
instead of actual CU values.

Adds:
- cu_to_dollar: conversion rate (default 10.0, meaning 1 CU = $10)
- input_cu_rate: generated column, auto-computed CU rate for input
- output_cu_rate: generated column, auto-computed CU rate for output

Formula: cu_rate = (dollar_rate * markup_multiplier) / cu_to_dollar

Example after migration:
- GPT-4o: input_rate=$2.50, markup=3.0, cu_to_dollar=10.0
  -> input_cu_rate = (2.50 * 3.0) / 10.0 = 0.75 CU per 1M tokens
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6e7f8g9h0i1j'
down_revision: Union[str, None] = '5d6e7f8g9h0i'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add cu_to_dollar column (regular column with default)
    op.add_column(
        'model_pricing',
        sa.Column('cu_to_dollar', sa.Numeric(6, 2), nullable=False, server_default='10.0'),
        schema='assistants'
    )

    # Add generated columns for CU rates
    # Postgres 12+ supports GENERATED ALWAYS AS ... STORED
    op.execute("""
        ALTER TABLE assistants.model_pricing
        ADD COLUMN input_cu_rate NUMERIC(12,8)
        GENERATED ALWAYS AS ((input_rate * markup_multiplier) / cu_to_dollar) STORED
    """)

    op.execute("""
        ALTER TABLE assistants.model_pricing
        ADD COLUMN output_cu_rate NUMERIC(12,8)
        GENERATED ALWAYS AS ((output_rate * markup_multiplier) / cu_to_dollar) STORED
    """)


def downgrade() -> None:
    op.drop_column('model_pricing', 'output_cu_rate', schema='assistants')
    op.drop_column('model_pricing', 'input_cu_rate', schema='assistants')
    op.drop_column('model_pricing', 'cu_to_dollar', schema='assistants')
