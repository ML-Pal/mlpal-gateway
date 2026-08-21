"""Tenant connections: user-supplied serving sources (design doc
planning/designs/connections-byom.md).

kind='byok'  — a credential for a provider family we already serve; it serves
               catalog models (pricing/capabilities known, tags unchanged).
kind='byom'  — a credential + endpoint for the user's own infrastructure; it
               serves models the user registers in tenant_models under the
               reserved `user/` tag namespace.

The raw provider key NEVER lives here — only an opaque custody reference
(secrets-service id, or local AES-GCM blob) plus non-secret config and
display/status metadata.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mlpal_assistants_service.db.models.base import Base


class TenantConnection(Base):
    __tablename__ = "tenant_connections"
    # NOTE: overriding __table_args__ replaces Base's schema dict — the
    # schema entry must be restated or the ORM emits unqualified SQL.
    # byok uniqueness is a PARTIAL index (one credential per family/backend);
    # byom connections are unlimited per user, identified by id + name.
    __table_args__ = (
        Index(
            "uq_conn_byok_user_family_backend",
            "user_id",
            "family",
            "backend",
            unique=True,
            postgresql_where=text("kind = 'byok'"),
        ),
        Index(
            "uq_conn_byom_user_name",
            "user_id",
            "name",
            unique=True,
            postgresql_where=text("kind = 'byom'"),
        ),
        {"schema": "assistants"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False, default="byok")
    # byom display name ("my-vllm-box"); null for byok rows.
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # byok: provider family (anthropic|openai|google).
    # byom: wire dialect the endpoint speaks (phase 1: openai).
    family: Mapped[str] = mapped_column(String(32), nullable=False)
    # byok: first_party|azure. byom: always "custom".
    backend: Mapped[str] = mapped_column(String(32), nullable=False, default="first_party")
    # Opaque custody handle: secrets-service secret id, or "local:v1:…" blob.
    secret_ref: Mapped[str] = mapped_column(Text, nullable=False)
    driver: Mapped[str] = mapped_column(String(32), nullable=False)
    last4: Mapped[str] = mapped_column(String(8), nullable=False)
    # verified | invalid | unverified — set by the save-time probe and by
    # provider 401/403 attribution at serve time.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unverified")
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # If this credential fails: "mlpal" = auto-switch to MLPal deployment
    # keys (billed to their wallet), "none" = hard-stop the family until they
    # fix the key (never bill them). Founder decision 2026-08-19: their choice.
    # byom is always "none" — there is no catalog equivalent to switch to.
    fallback: Mapped[str] = mapped_column(String(16), nullable=False, default="mlpal")
    # Non-secret backend config (azure: endpoint + deployments map;
    # byom: endpoint URL).
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TenantModel(Base):
    """A user-registered model served by a byom connection. Tags live in the
    reserved `user/` namespace and are tenant-scoped — deliberately NOT in
    model_registry, never in shared caches, the feed, or meta-model routing.
    Pricing is user-declared metadata for their cost visibility (mandatory,
    founder decision), never a billable rate."""

    __tablename__ = "tenant_models"
    __table_args__ = (
        UniqueConstraint("user_id", "model_tag", name="uq_tenant_model_user_tag"),
        {"schema": "assistants"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("assistants.tenant_connections.id"), nullable=False, index=True
    )
    # Immutable after create (usage history references it); ^user/…$ enforced
    # at the API boundary.
    model_tag: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_model_id: Mapped[str] = mapped_column(String(256), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False, default="chat")
    context_length: Mapped[int] = mapped_column(Integer, nullable=False)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # USD per 1M tokens, user-declared.
    input_price_per_m: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    output_price_per_m: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    capabilities: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Optional explicit catalog stand-in (phase-2 affordance, no UI yet).
    fallback_model_tag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
