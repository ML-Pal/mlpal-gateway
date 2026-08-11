"""Add cc_metadata JSONB column to usage_logs.

Captures Claude Code session attribution (session_id, agent_id,
parent_agent_id, anthropic_user_id, beta headers) on every /v1/messages
call. We already capture these in structured logs; this column makes
them queryable for per-session billing dashboards and abuse triage
without paying the log-aggregation cost.

The column is JSONB (not a set of columns) because the shape may grow
over time as Claude Code adds attribution headers, and we want to add
fields without further migrations.

Revision ID: 20260527_2300
Revises: 20260406_0105
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260527_2300"
down_revision: str | Sequence[str] | None = "20260406_0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "usage_logs",
        sa.Column(
            "cc_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema="assistants",
    )
    # GIN index for ad-hoc filtering on metadata fields, e.g. find all
    # rows for a given Claude Code session id. Cheap to maintain at our
    # write rate; speeds dashboard queries dramatically.
    op.create_index(
        "idx_usage_cc_metadata_gin",
        "usage_logs",
        ["cc_metadata"],
        unique=False,
        postgresql_using="gin",
        schema="assistants",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_usage_cc_metadata_gin",
        table_name="usage_logs",
        schema="assistants",
    )
    op.drop_column("usage_logs", "cc_metadata", schema="assistants")
