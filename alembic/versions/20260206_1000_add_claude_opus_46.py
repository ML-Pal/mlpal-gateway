"""add_claude_opus_46

Revision ID: 5d6e7f8g9h0i
Revises: 4c5d6e7f8g9h
Create Date: 2026-02-06 10:00:00.000000

Adds Claude Opus 4.6, Anthropic's latest flagship model released February 5, 2026.

Key features:
- API ID: claude-opus-4-6
- Context: 200K standard, 1M beta (via context-1m-2025-08-07 header)
- Output: 128K tokens (2x previous)
- Adaptive thinking with effort levels (low/medium/high/max)
- Agent teams for parallel multi-agent execution
- Context compaction for infinite conversations

Pricing: $5/M input, $25/M output (standard); $10/M input, $37.50/M output (1M context)
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '5d6e7f8g9h0i'
down_revision: Union[str, None] = '4c5d6e7f8g9h'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Insert Claude Opus 4.6 into model_registry
    op.execute("""
        INSERT INTO assistants.model_registry (
            model_tag, provider, provider_model_id, display_name, description,
            capabilities, context_length, max_output_tokens, pricing_tier,
            priority, is_active, is_deprecated
        ) VALUES (
            'claude-opus-4-6',
            'anthropic',
            'claude-opus-4-6',
            'Claude Opus 4.6',
            'Anthropic''s latest flagship model with 1M context (beta), 128K output, adaptive thinking, agent teams, and context compaction. Released Feb 5, 2026.',
            '["chat", "vision", "function_calling", "structured_output", "streaming", "pdf"]'::jsonb,
            200000,
            128000,
            'premium',
            0,
            true,
            false
        )
        ON CONFLICT (model_tag) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            description = EXCLUDED.description,
            capabilities = EXCLUDED.capabilities,
            context_length = EXCLUDED.context_length,
            max_output_tokens = EXCLUDED.max_output_tokens,
            updated_at = now()
    """)

    # Insert pricing for Claude Opus 4.6 (standard context <=200K)
    op.execute("""
        INSERT INTO assistants.model_pricing (
            model_tag, operation, tier, input_rate, output_rate,
            rate_unit, markup_multiplier, effective_date, is_active
        ) VALUES (
            'claude-opus-4-6',
            'chat',
            'premium',
            5.00,
            25.00,
            'per_1m_tokens',
            3.0,
            '2026-02-06',
            true
        )
        ON CONFLICT (model_tag, operation, effective_date) DO UPDATE SET
            input_rate = EXCLUDED.input_rate,
            output_rate = EXCLUDED.output_rate,
            updated_at = now()
    """)


def downgrade() -> None:
    # Remove pricing
    op.execute("""
        DELETE FROM assistants.model_pricing
        WHERE model_tag = 'claude-opus-4-6'
        AND effective_date = '2026-02-06'
    """)

    # Remove model
    op.execute("""
        DELETE FROM assistants.model_registry
        WHERE model_tag = 'claude-opus-4-6'
    """)
