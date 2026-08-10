"""Delegation-outcome feedback — the measured signal behind catalog rankings.

A coding harness (yodex) runs its main loop on a strong model and delegates
subtasks to cheaper/specialized models through the gateway. The outcome of each
delegation is real, in-context quality data the gateway can aggregate into
per-model, per-task-type quality — a feedback loop that replaces static
leaderboard judgement as traffic accrues.

Each row is one delegation outcome. `escalated` is the strongest signal: the
model wasn't good enough and the caller had to redo the subtask on a stronger
one (recorded in `escalated_to`) — a direct comparative quality datum.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from mlpal_assistants_service.db.models.base import Base

# Controlled outcome vocabulary. Ordered worst→best is intentional (see
# repository scoring); keep in sync with the /v2/feedback validator.
FEEDBACK_OUTCOMES = ("failed", "escalated", "retried", "accepted")


class ModelFeedback(Base):
    """One delegation outcome for (model_tag, task_type)."""

    __tablename__ = "model_feedback"
    __table_args__ = (
        Index("idx_feedback_model_task", "model_tag", "task_type", "created_at"),
        Index("idx_feedback_created", "created_at"),  # windowed aggregation + pruning
        {"schema": "assistants"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=False
    )

    # Attribution (cross-schema ids, no FK — matches usage_logs).
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    api_key_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    model_tag: Mapped[str] = mapped_column(String(100), nullable=False)
    # Task dimension the delegation was for (coding / reasoning / tool_use / …).
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # One of FEEDBACK_OUTCOMES.
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    # On `escalated`, the model the caller succeeded with instead (comparative).
    escalated_to: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Optional link back to the originating request in usage_logs.
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    def __repr__(self) -> str:
        return f"<ModelFeedback({self.model_tag}/{self.task_type}={self.outcome})>"
