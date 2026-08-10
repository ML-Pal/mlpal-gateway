"""Delegation-outcome feedback: record events, aggregate into measured quality.

The aggregate is the whole point — per (model, task_type) it turns raw outcomes
into a 0–100 quality score the catalog can rank on, replacing static leaderboard
seeding as real traffic accrues. Below `min_samples` a model/task pair is omitted
(callers fall back to the benchmark seed) rather than published on thin data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select

from mlpal_assistants_service.db.models import ModelFeedback
from mlpal_assistants_service.repositories.base import BaseRepository

# Outcome → quality weight. `accepted` is full credit; `retried` succeeded but
# needed a second attempt (partial); `escalated`/`failed` are misses. Escalation
# is also surfaced separately as a comparative signal (which model won instead).
_OUTCOME_WEIGHT = {"accepted": 1.0, "retried": 0.6, "escalated": 0.0, "failed": 0.0}


class FeedbackRepository(BaseRepository[ModelFeedback]):
    model = ModelFeedback

    async def record(
        self,
        model_tag: str,
        task_type: str,
        outcome: str,
        user_id: int | None = None,
        api_key_id: int | None = None,
        escalated_to: str | None = None,
        trace_id: str | None = None,
    ) -> ModelFeedback:
        return await self.create(
            model_tag=model_tag,
            task_type=task_type,
            outcome=outcome,
            user_id=user_id,
            api_key_id=api_key_id,
            escalated_to=escalated_to,
            trace_id=trace_id,
        )

    async def get_quality_by_model(
        self,
        days: int = 30,
        min_samples: int = 30,
    ) -> dict[str, dict[str, dict]]:
        """Measured quality per model, nested {model_tag: {task_type: stats}}.

        stats = {score 0–100, samples, accept_rate, escalation_rate}. Only pairs
        with >= min_samples in the window are returned.
        """
        since = datetime.now(UTC) - timedelta(days=days)
        weight = case(_OUTCOME_WEIGHT, value=ModelFeedback.outcome, else_=0.0)
        is_accepted = case((ModelFeedback.outcome == "accepted", 1.0), else_=0.0)
        is_escalated = case((ModelFeedback.outcome == "escalated", 1.0), else_=0.0)
        stmt = (
            select(
                ModelFeedback.model_tag,
                ModelFeedback.task_type,
                func.count().label("samples"),
                func.avg(weight).label("score_frac"),
                func.avg(is_accepted).label("accept_rate"),
                func.avg(is_escalated).label("escalation_rate"),
            )
            .where(ModelFeedback.created_at >= since)
            .group_by(ModelFeedback.model_tag, ModelFeedback.task_type)
            .having(func.count() >= min_samples)
        )
        result = await self.session.execute(stmt)
        out: dict[str, dict[str, dict]] = {}
        for row in result:
            out.setdefault(row.model_tag, {})[row.task_type] = {
                "score": round(float(row.score_frac) * 100, 1),
                "samples": int(row.samples),
                "accept_rate": round(float(row.accept_rate), 3),
                "escalation_rate": round(float(row.escalation_rate), 3),
            }
        return out
