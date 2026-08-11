"""Add `source` provenance to model_registry.

Distinguishes rows owned by the MLPal curated **feed** from rows an operator
added **locally** (custom models / private fine-tunes). The catalog reconcile
only ever inserts/updates/soft-retires `source='mlpal-feed'` rows — it never
touches `source='local'` — so a feed refresh can't clobber or retire an
operator's own models. Existing rows backfill to 'mlpal-feed'.

Revision ID: 20260805_1200
Revises: 20260802_1200
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_1200"
down_revision: str | Sequence[str] | None = "20260802_1200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_registry",
        sa.Column(
            "source", sa.String(length=32), nullable=False, server_default="mlpal-feed"
        ),
        schema="assistants",
    )
    op.create_index(
        "idx_model_registry_source", "model_registry", ["source"], schema="assistants"
    )


def downgrade() -> None:
    op.drop_index("idx_model_registry_source", "model_registry", schema="assistants")
    op.drop_column("model_registry", "source", schema="assistants")
