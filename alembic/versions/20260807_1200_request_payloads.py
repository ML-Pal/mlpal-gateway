"""request_payloads — opt-in captured request/response bodies.

zlib-compressed bytes, size-capped, retention-purged. Capture is OFF by
default (privacy); the table exists so the operator can flip it on without a
migration. See services/capture.py + planning/console-v2/DESIGN-payload-capture.md.

Revision ID: 20260807_1200
Revises: 20260805_1200
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_1200"
down_revision: Union[str, Sequence[str], None] = "20260805_1200"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "request_payloads",
        sa.Column("trace_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("request_gz", sa.LargeBinary(), nullable=False),
        sa.Column("response_gz", sa.LargeBinary(), nullable=False),
        sa.Column("request_bytes", sa.Integer(), nullable=False),
        sa.Column("response_bytes", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), server_default=sa.false(), nullable=False),
        schema="assistants",
    )
    op.create_index(
        "idx_request_payloads_created", "request_payloads", ["created_at"], schema="assistants"
    )


def downgrade() -> None:
    op.drop_index("idx_request_payloads_created", "request_payloads", schema="assistants")
    op.drop_table("request_payloads", schema="assistants")
