"""Add tags JSONB column to api_keys.

Used by service callers (e.g., mcp-service minting cde_sk_* keys for
builder CDE pods) to record what entity the key belongs to. Primary
read path is still the FK column on the owning service's table; tags
exist as a belt-and-suspenders attribution channel so the cde_sk_ key
can be traced back to its owner even if the owning row is lost.

Revision ID: 20260604_1200
Revises: 20260527_2300
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260604_1200"
down_revision: Union[str, Sequence[str], None] = "20260527_2300"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        schema="assistants",
    )
    op.create_index(
        "idx_api_keys_tags_gin",
        "api_keys",
        ["tags"],
        unique=False,
        postgresql_using="gin",
        schema="assistants",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_api_keys_tags_gin",
        table_name="api_keys",
        schema="assistants",
    )
    op.drop_column("api_keys", "tags", schema="assistants")
