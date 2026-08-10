"""Opt-in captured request/response payloads (see services/capture.py).

Separate from usage_logs on purpose: payloads are heavy, optional, and
short-lived (retention-purged); the metering table stays lean and permanent.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from mlpal_assistants_service.db.models.base import Base


class RequestPayload(Base):
    __tablename__ = "request_payloads"
    __table_args__ = (
        # Retention purge scans by age.
        Index("idx_request_payloads_created", "created_at"),
        {"schema": "assistants"},
    )

    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # zlib-compressed UTF-8 (JSON or raw text), capped + truncation-flagged.
    request_gz: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    response_gz: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    request_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    response_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        return f"<RequestPayload(trace={self.trace_id}, truncated={self.truncated})>"
