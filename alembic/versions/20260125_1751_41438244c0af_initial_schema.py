"""initial_schema

Revision ID: 41438244c0af
Revises:
Create Date: 2026-01-25 17:51:26.722423

Note: Users are managed in a separate schema (configured via MLPAL_USER_SCHEMA).
The api_keys and usage_logs tables reference user_id but without FK constraints,
as the user schema may vary between environments.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '41438244c0af'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = 'assistants'


def upgrade() -> None:
    # Create schema if it doesn't exist
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # Model pricing - stores pricing tiers for different models
    op.create_table('model_pricing',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('model_tag', sa.String(length=100), nullable=False),
        sa.Column('operation', sa.String(length=50), nullable=False),
        sa.Column('tier', sa.String(length=20), nullable=False),
        sa.Column('input_rate', sa.Numeric(precision=12, scale=8), nullable=False),
        sa.Column('output_rate', sa.Numeric(precision=12, scale=8), nullable=False),
        sa.Column('rate_unit', sa.String(length=50), nullable=False),
        sa.Column('markup_multiplier', sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('model_tag', 'operation', 'effective_date', name='uq_pricing'),
        schema=SCHEMA
    )
    op.create_index('idx_pricing_effective', 'model_pricing', ['effective_date'], schema=SCHEMA)
    op.create_index('idx_pricing_model_op', 'model_pricing', ['model_tag', 'operation'], schema=SCHEMA)

    # Model registry - catalog of available models
    op.create_table('model_registry',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('model_tag', sa.String(length=100), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('provider_model_id', sa.String(length=200), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=1000), nullable=True),
        sa.Column('capabilities', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('context_length', sa.Integer(), nullable=True),
        sa.Column('max_output_tokens', sa.Integer(), nullable=True),
        sa.Column('pricing_tier', sa.String(length=50), nullable=False),
        sa.Column('fallback_model_tag', sa.String(length=100), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_deprecated', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('deprecation_message', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('model_tag'),
        schema=SCHEMA
    )
    op.create_index('idx_model_registry_active', 'model_registry', ['is_active'], schema=SCHEMA)
    op.create_index('idx_model_registry_provider', 'model_registry', ['provider'], schema=SCHEMA)
    op.create_index('idx_model_registry_tag', 'model_registry', ['model_tag'], unique=True, schema=SCHEMA)

    # API keys for MLpal assistants service
    # user_id references the main users table in the configured user schema (no FK constraint)
    op.create_table('api_keys',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),  # References {user_schema}.users.id
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('key_prefix', sa.String(length=30), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('permissions', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('rate_limit_tier', sa.String(length=50), nullable=False, server_default="'standard'"),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key_hash'),
        schema=SCHEMA
    )
    op.create_index('idx_api_keys_hash', 'api_keys', ['key_hash'], unique=True, schema=SCHEMA)
    op.create_index('idx_api_keys_user', 'api_keys', ['user_id'], schema=SCHEMA)
    op.create_index('idx_api_keys_user_active', 'api_keys', ['user_id'], schema=SCHEMA,
                    postgresql_where=sa.text('is_active = true'))

    # Usage logs for tracking API usage
    # user_id references the main users table in the configured user schema (no FK constraint)
    op.create_table('usage_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),  # References {user_schema}.users.id
        sa.Column('api_key_id', sa.Integer(), nullable=False),
        sa.Column('trace_id', sa.String(length=50), nullable=False),
        sa.Column('model_tag', sa.String(length=100), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('operation', sa.String(length=50), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('compute_units', sa.Numeric(precision=12, scale=6), nullable=False, server_default='0'),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('error_code', sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint('id', 'created_at'),
        sa.ForeignKeyConstraint(['api_key_id'], [f'{SCHEMA}.api_keys.id'], ondelete='CASCADE'),
        schema=SCHEMA
    )
    op.create_index('idx_usage_api_key', 'usage_logs', ['api_key_id', 'created_at'], schema=SCHEMA)
    op.create_index('idx_usage_model', 'usage_logs', ['model_tag', 'created_at'], schema=SCHEMA)
    op.create_index('idx_usage_user', 'usage_logs', ['user_id', 'created_at'], schema=SCHEMA)
    op.create_index('idx_usage_trace', 'usage_logs', ['trace_id'], schema=SCHEMA)


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_index('idx_usage_trace', table_name='usage_logs', schema=SCHEMA)
    op.drop_index('idx_usage_user', table_name='usage_logs', schema=SCHEMA)
    op.drop_index('idx_usage_model', table_name='usage_logs', schema=SCHEMA)
    op.drop_index('idx_usage_api_key', table_name='usage_logs', schema=SCHEMA)
    op.drop_table('usage_logs', schema=SCHEMA)

    op.drop_index('idx_api_keys_user_active', table_name='api_keys', schema=SCHEMA,
                  postgresql_where=sa.text('is_active = true'))
    op.drop_index('idx_api_keys_user', table_name='api_keys', schema=SCHEMA)
    op.drop_index('idx_api_keys_hash', table_name='api_keys', schema=SCHEMA)
    op.drop_table('api_keys', schema=SCHEMA)

    op.drop_index('idx_model_registry_tag', table_name='model_registry', schema=SCHEMA)
    op.drop_index('idx_model_registry_provider', table_name='model_registry', schema=SCHEMA)
    op.drop_index('idx_model_registry_active', table_name='model_registry', schema=SCHEMA)
    op.drop_table('model_registry', schema=SCHEMA)

    op.drop_index('idx_pricing_model_op', table_name='model_pricing', schema=SCHEMA)
    op.drop_index('idx_pricing_effective', table_name='model_pricing', schema=SCHEMA)
    op.drop_table('model_pricing', schema=SCHEMA)
