"""Model Registry - stores available AI models and their configuration."""

from sqlalchemy import Boolean, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mlpal_assistants_service.db.models.base import Base, TimestampMixin


class ModelRegistry(Base, TimestampMixin):
    """
    Model registry table.

    Stores information about available AI models, their capabilities,
    and routing configuration.
    """

    __tablename__ = "model_registry"
    __table_args__ = (
        Index("idx_model_registry_tag", "model_tag", unique=True),
        Index("idx_model_registry_provider", "provider"),
        Index("idx_model_registry_active", "is_active"),
        {"schema": "assistants"},
    )

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Model identification
    model_tag: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    # Provider info
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    provider_model_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    # Display name for UI
    display_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    # Description
    description: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    # Capabilities (JSON array)
    # e.g., ["chat", "vision", "function_calling", "structured_output"]
    capabilities: Mapped[list[str]] = mapped_column(
        JSONB,
        default=["chat"],
        nullable=False,
    )

    # Model specifications
    context_length: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    max_output_tokens: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # Pricing tier (budget, standard, premium)
    pricing_tier: Mapped[str] = mapped_column(
        String(50),
        default="standard",
        nullable=False,
    )

    # Fallback configuration
    fallback_model_tag: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # Priority for routing (lower = higher priority)
    priority: Mapped[int] = mapped_column(
        Integer,
        default=100,
        nullable=False,
    )

    # Status
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Deprecation info
    is_deprecated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    deprecation_message: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # Pause: registered and visible, but temporarily not callable (e.g. an
    # upstream provider suspended the model). Distinct from is_active (hard
    # disable) and is_deprecated (sunset warning). Paused models raise
    # ModelNotAvailableError with pause_reason and can be un-paused in place.
    is_paused: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    pause_reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # Provenance: "mlpal-feed" (owned by the curated feed; the reconcile may
    # insert/update/soft-retire it) or "local" (operator-added; the feed never
    # touches it). See services/catalog_sync.py.
    source: Mapped[str] = mapped_column(
        String(32),
        default="mlpal-feed",
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<ModelRegistry(tag={self.model_tag}, provider={self.provider})>"

    def has_capability(self, capability: str) -> bool:
        """Check if model has a specific capability."""
        return capability in self.capabilities
