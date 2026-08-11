"""Widen usage_logs.compute_units to numeric(24,12).

numeric(12,6) truncates pass-through CU below 5e-7 to ZERO — prod showed
zeroed success rows for cheap models (gemini-flash-lite ~2.4e-7 CU/request,
gpt-5-nano small turns). The response/header figure was always correct; only
persistence truncated. 24,12 matches the resolution payments is adopting for
wallet columns, so the figure survives end-to-end.

Revision ID: 20260811_2000
Revises: 20260811_1200
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260811_2000"
down_revision: str | Sequence[str] | None = "20260811_1200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE assistants.usage_logs "
        "ALTER COLUMN compute_units TYPE numeric(24,12)"
    )


def downgrade() -> None:
    # Narrowing back would re-truncate small values; only for emergencies.
    op.execute(
        "ALTER TABLE assistants.usage_logs "
        "ALTER COLUMN compute_units TYPE numeric(12,6)"
    )
