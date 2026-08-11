"""Router-tag candidate lists: unique index gains priority.

The old partial unique index on (meta_model_tag, operation) enforced a single
active winner per operation. Routing is now a priority-ordered candidate list
resolved against availability at request time, so uniqueness moves to
(meta_model_tag, operation, priority).

Revision ID: 20260811_1200
Revises: 20260807_1200
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260811_1200"
down_revision: str | Sequence[str] | None = "20260807_1200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS assistants.idx_meta_routing_unique_active")
    op.execute(
        """
        CREATE UNIQUE INDEX idx_meta_routing_unique_active
        ON assistants.meta_model_routing (meta_model_tag, operation, priority)
        WHERE is_active = true
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS assistants.idx_meta_routing_unique_active")
    op.execute(
        """
        CREATE UNIQUE INDEX idx_meta_routing_unique_active
        ON assistants.meta_model_routing (meta_model_tag, operation)
        WHERE is_active = true
        """
    )
