"""catalog feed: gateway_meta kv + feed_installs

Revision ID: 20260812_1000
Revises: 20260811_2200
Create Date: 2026-08-12
"""

import sqlalchemy as sa
from alembic import op

revision = "20260812_1000"
down_revision = "20260811_2200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gateway_meta",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.String(256), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="assistants",
    )
    op.create_table(
        "feed_installs",
        sa.Column("instance_id", sa.String(64), primary_key=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gateway_version", sa.String(64), nullable=True),
        sa.Column("pull_count", sa.Integer(), nullable=False, server_default="1"),
        schema="assistants",
    )


def downgrade() -> None:
    op.drop_table("feed_installs", schema="assistants")
    op.drop_table("gateway_meta", schema="assistants")
