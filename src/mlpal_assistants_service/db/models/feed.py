"""Catalog-feed tables: per-deployment identity and subscriber installs.

``gateway_meta`` is a tiny key/value store for deployment-lifetime facts —
today just ``instance_id``, the anonymous UUID a subscribing box sends with
feed pulls. ``feed_installs`` is the feed-SERVER side: one row per subscribing
instance, upserted on every pull, which is how the feed operator counts active
installs and their versions.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from mlpal_assistants_service.db.models.base import Base


class GatewayMeta(Base):
    __tablename__ = "gateway_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FeedInstall(Base):
    __tablename__ = "feed_installs"

    instance_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gateway_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pull_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
