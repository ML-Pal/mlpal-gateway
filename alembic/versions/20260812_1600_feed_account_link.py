"""feed_installs: link installs to accounts; drop the header-email path

Revision ID: 20260812_1600
Revises: 20260812_1400
Create Date: 2026-08-12
"""

import sqlalchemy as sa
from alembic import op

revision = "20260812_1600"
down_revision = "20260812_1400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "feed_installs", sa.Column("user_id", sa.Integer(), nullable=True), schema="assistants"
    )
    op.add_column(
        "feed_installs", sa.Column("api_key_id", sa.Integer(), nullable=True), schema="assistants"
    )
    # Registration replaces the optional header email (account email is
    # verified; the header one never was).
    op.drop_column("feed_installs", "email", schema="assistants")


def downgrade() -> None:
    op.add_column(
        "feed_installs", sa.Column("email", sa.String(320), nullable=True), schema="assistants"
    )
    op.drop_column("feed_installs", "api_key_id", schema="assistants")
    op.drop_column("feed_installs", "user_id", schema="assistants")
