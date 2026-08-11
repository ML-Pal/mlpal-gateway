"""add_meta_model_routing

Revision ID: 3b4c5d6e7f8g
Revises: 2b3c4d5e6f7g
Create Date: 2026-01-27 12:00:00.000000

Adds meta_model_routing table for MLPal mixture-of-experts routing.
This table maps MLPal meta-models (mlpal, mlpal-flash, mlpal-lite)
to actual provider models based on operation type.

MLPal Meta-Models:
- mlpal: Best quality, routes to state-of-the-art models
- mlpal-flash: Fastest, routes to low-latency models
- mlpal-lite: Most economical, routes to cost-optimized models
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '4c5d6e7f8g9h'
down_revision: str | None = '3b4c5d6e7f8a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Routing rules: (meta_model_tag, operation, resolved_model_tag, reason)
ROUTING_RULES = [
    # =========================================================================
    # mlpal - Best Quality
    # =========================================================================
    ("mlpal", "chat", "gpt-5.2",
     "GPT-5.2 is the latest flagship with 400K context and thinking capabilities"),
    ("mlpal", "image_generation", "gemini-3-pro-image-preview",
     "Gemini 3 Pro Image is best quality, supports 14 reference images"),
    ("mlpal", "tts", "tts-1-hd",
     "TTS-1-HD has the most natural, high-quality voice output"),
    ("mlpal", "transcription", "gpt-4o-transcribe",
     "GPT-4o Transcribe has highest accuracy for speech recognition"),
    ("mlpal", "embedding", "text-embedding-3-large",
     "3072 dimensions provides highest semantic fidelity"),
    ("mlpal", "structured_output", "gpt-5.2",
     "GPT-5.2 excels at following JSON schemas precisely"),

    # =========================================================================
    # mlpal-flash - Fastest
    # =========================================================================
    ("mlpal-flash", "chat", "gemini-3-flash-preview",
     "Gemini 3 Flash is optimized for speed with 1M context"),
    ("mlpal-flash", "image_generation", "gpt-image-1",
     "GPT Image 1 offers fast, reliable image generation"),
    ("mlpal-flash", "tts", "tts-1",
     "TTS-1 is the standard fast option for text-to-speech"),
    ("mlpal-flash", "transcription", "gpt-4o-mini-transcribe",
     "GPT-4o Mini Transcribe is 2x faster than full model"),
    ("mlpal-flash", "embedding", "text-embedding-3-small",
     "1536 dimensions, faster processing than large"),
    ("mlpal-flash", "structured_output", "gemini-3-flash-preview",
     "Gemini 3 Flash provides good structured output with low latency"),

    # =========================================================================
    # mlpal-lite - Most Economical
    # =========================================================================
    ("mlpal-lite", "chat", "gpt-5-nano",
     "GPT-5 Nano at $0.05/$0.40 per 1M tokens - 35x cheaper than GPT-5.2"),
    ("mlpal-lite", "image_generation", "gpt-image-1-mini",
     "GPT Image 1 Mini is the most cost-effective image model"),
    ("mlpal-lite", "tts", "gpt-4o-mini-tts",
     "GPT-4o Mini TTS at $12/1M chars is cheapest option"),
    ("mlpal-lite", "transcription", "gpt-4o-mini-transcribe",
     "GPT-4o Mini Transcribe at $0.003/min - 50% cheaper"),
    ("mlpal-lite", "embedding", "gemini-embedding-001",
     "Gemini Embedding 001 is cost-effective with high quality"),
    ("mlpal-lite", "structured_output", "gpt-5-nano",
     "GPT-5 Nano supports structured output at lowest cost"),
]

# MLPal meta-model entries for model_registry
META_MODELS = [
    ("mlpal", "MLPal Best", "Best quality models for each operation"),
    ("mlpal-flash", "MLPal Flash", "Fastest models optimized for low latency"),
    ("mlpal-lite", "MLPal Lite", "Most cost-effective models for high volume"),
]


def upgrade() -> None:
    # Create meta_model_routing table
    op.create_table(
        'meta_model_routing',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('meta_model_tag', sa.String(length=50), nullable=False,
                  comment="Meta model tag: mlpal, mlpal-flash, mlpal-lite"),
        sa.Column('operation', sa.String(length=50), nullable=False,
                  comment="Operation: chat, image_generation, tts, transcription, embedding, structured_output"),
        sa.Column('resolved_model_tag', sa.String(length=100), nullable=False,
                  comment="Actual model tag to use (must exist in model_registry)"),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0',
                  comment="Priority for fallback ordering (0 = primary)"),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('reason', sa.String(length=500), nullable=True,
                  comment="Why this model was chosen for this operation"),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        schema='assistants'
    )

    # Create indexes
    op.create_index(
        'idx_meta_routing_lookup',
        'meta_model_routing',
        ['meta_model_tag', 'operation', 'is_active'],
        schema='assistants'
    )

    # Partial unique index for active routings
    op.execute("""
        CREATE UNIQUE INDEX idx_meta_routing_unique_active
        ON assistants.meta_model_routing (meta_model_tag, operation)
        WHERE is_active = true
    """)

    # Insert MLPal meta-models into model_registry
    for tag, display_name, description in META_MODELS:
        op.execute(f"""
            INSERT INTO assistants.model_registry (
                model_tag, provider, provider_model_id, display_name, description,
                capabilities, context_length, max_output_tokens, pricing_tier,
                priority, is_active, is_deprecated
            ) VALUES (
                '{tag}', 'mlpal', '{tag}', '{display_name}', '{description}',
                '["chat", "image_generation", "tts", "transcription", "embedding", "structured_output"]'::jsonb,
                NULL, NULL, 'dynamic', 0, true, false
            )
            ON CONFLICT (model_tag) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                description = EXCLUDED.description,
                is_active = true
        """)

    # Insert routing rules
    for meta_tag, operation, resolved_tag, reason in ROUTING_RULES:
        # Escape single quotes in reason
        safe_reason = reason.replace("'", "''")
        op.execute(f"""
            INSERT INTO assistants.meta_model_routing (
                meta_model_tag, operation, resolved_model_tag, priority, is_active, reason
            ) VALUES (
                '{meta_tag}', '{operation}', '{resolved_tag}', 0, true, '{safe_reason}'
            )
        """)


def downgrade() -> None:
    # Remove routing rules
    op.execute("DELETE FROM assistants.meta_model_routing")

    # Remove meta-models from model_registry
    for tag, _, _ in META_MODELS:
        op.execute(f"DELETE FROM assistants.model_registry WHERE model_tag = '{tag}'")

    # Drop indexes and table
    op.execute("DROP INDEX IF EXISTS assistants.idx_meta_routing_unique_active")
    op.drop_index('idx_meta_routing_lookup', table_name='meta_model_routing', schema='assistants')
    op.drop_table('meta_model_routing', schema='assistants')
