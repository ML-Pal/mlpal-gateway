"""feed_installs: optional contact email

Revision ID: 20260812_1400
Revises: 20260812_1000
Create Date: 2026-08-12
"""

import sqlalchemy as sa
from alembic import op

revision = "20260812_1400"
down_revision = "20260812_1000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "feed_installs",
        sa.Column("email", sa.String(320), nullable=True),
        schema="assistants",
    )


def downgrade() -> None:
    op.drop_column("feed_installs", "email", schema="assistants")
