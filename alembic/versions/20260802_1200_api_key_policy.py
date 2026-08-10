"""Add per-key policy columns (model_policy, budgets) to api_keys.

Powers the per-key policy engine (services/policy.py): model allow/deny lists
and spend budgets. Both nullable with no default — NULL = unrestricted, so
every existing key keeps full access and no backfill is required.

Revision ID: 20260802_1200
Revises: 20260724_1200
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260802_1200"
down_revision: Union[str, Sequence[str], None] = "20260724_1200"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("model_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="assistants",
    )
    op.add_column(
        "api_keys",
        sa.Column("budgets", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="assistants",
    )


def downgrade() -> None:
    op.drop_column("api_keys", "budgets", schema="assistants")
    op.drop_column("api_keys", "model_policy", schema="assistants")
