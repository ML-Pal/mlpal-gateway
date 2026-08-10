"""Add model_feedback table — delegation-outcome signal for catalog rankings.

Stores one row per delegated-subtask outcome (accepted/retried/escalated/failed)
per (model_tag, task_type), aggregated into measured per-model quality that
replaces static leaderboard seeding as traffic accrues.

Revision ID: 20260724_1200
Revises: 20260621_1200
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_1200"
down_revision: Union[str, Sequence[str], None] = "20260621_1200"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("api_key_id", sa.Integer(), nullable=True),
        sa.Column("model_tag", sa.String(length=100), nullable=False),
        sa.Column("task_type", sa.String(length=50), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("escalated_to", sa.String(length=100), nullable=True),
        sa.Column("trace_id", sa.String(length=100), nullable=True),
        schema="assistants",
    )
    op.create_index(
        "idx_feedback_model_task", "model_feedback",
        ["model_tag", "task_type", "created_at"], schema="assistants",
    )
    op.create_index(
        "idx_feedback_created", "model_feedback", ["created_at"], schema="assistants",
    )


def downgrade() -> None:
    op.drop_index("idx_feedback_created", "model_feedback", schema="assistants")
    op.drop_index("idx_feedback_model_task", "model_feedback", schema="assistants")
    op.drop_table("model_feedback", schema="assistants")
