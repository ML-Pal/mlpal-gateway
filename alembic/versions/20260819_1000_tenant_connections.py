"""tenant_connections + tenant_models: user-supplied serving sources

BYOK credentials and BYOM custom endpoints/models, unified (design doc
planning/designs/connections-byom.md). No raw secrets — custody refs only.

Revision ID: 20260819_1000
Revises: 20260812_1600
Create Date: 2026-08-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260819_1000"
down_revision = "20260812_1600"
branch_labels = None
depends_on = None

SCHEMA = "assistants"


def upgrade() -> None:
    op.create_table(
        "tenant_connections",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False, index=True),
        sa.Column("kind", sa.String(8), nullable=False, server_default="byok"),
        sa.Column("name", sa.String(64), nullable=True),
        sa.Column("family", sa.String(32), nullable=False),
        sa.Column("backend", sa.String(32), nullable=False, server_default="first_party"),
        sa.Column("secret_ref", sa.Text, nullable=False),
        sa.Column("driver", sa.String(32), nullable=False),
        sa.Column("last4", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="unverified"),
        sa.Column("error", sa.String(300), nullable=True),
        sa.Column("fallback", sa.String(16), nullable=False, server_default="mlpal"),
        sa.Column("config", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_conn_byok_user_family_backend",
        "tenant_connections",
        ["user_id", "family", "backend"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("kind = 'byok'"),
    )
    op.create_index(
        "uq_conn_byom_user_name",
        "tenant_connections",
        ["user_id", "name"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("kind = 'byom'"),
    )
    op.create_table(
        "tenant_models",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False, index=True),
        sa.Column(
            "connection_id",
            sa.Integer,
            sa.ForeignKey(f"{SCHEMA}.tenant_connections.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("model_tag", sa.String(128), nullable=False),
        sa.Column("provider_model_id", sa.String(256), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False, server_default="chat"),
        sa.Column("context_length", sa.Integer, nullable=False),
        sa.Column("max_output_tokens", sa.Integer, nullable=True),
        sa.Column("input_price_per_m", sa.Numeric(12, 6), nullable=False),
        sa.Column("output_price_per_m", sa.Numeric(12, 6), nullable=False),
        sa.Column("capabilities", JSONB, nullable=True),
        sa.Column("fallback_model_tag", sa.String(128), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "model_tag", name="uq_tenant_model_user_tag"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("tenant_models", schema=SCHEMA)
    op.drop_table("tenant_connections", schema=SCHEMA)
