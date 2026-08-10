"""Add is_paused + pause_reason to model_registry.

A "paused" model is registered and visible but temporarily not callable — e.g.
an upstream provider suspends a model (Claude Fable 5 was paused by Anthropic
shortly after launch). This is deliberately distinct from:
  * is_active=false   — hard admin disable / retired
  * is_deprecated=true — sunset warning, still callable
A paused model raises ModelNotAvailableError with its pause_reason (HTTP 503),
and can be un-paused without re-adding it.

Revision ID: 20260621_1200
Revises: 20260604_1200
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260621_1200"
down_revision: Union[str, Sequence[str], None] = "20260604_1200"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "model_registry",
        sa.Column("is_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="assistants",
    )
    op.add_column(
        "model_registry",
        sa.Column("pause_reason", sa.String(length=500), nullable=True),
        schema="assistants",
    )


def downgrade() -> None:
    op.drop_column("model_registry", "pause_reason", schema="assistants")
    op.drop_column("model_registry", "is_paused", schema="assistants")
