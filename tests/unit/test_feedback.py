"""Feedback repository aggregation + the /v2/feedback validation contract."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from mlpal_assistants_service.db.models import FEEDBACK_OUTCOMES
from mlpal_assistants_service.repositories.feedback_repository import (
    _OUTCOME_WEIGHT,
    FeedbackRepository,
)


def test_outcome_weights_ordered_and_cover_vocab():
    # Every outcome has a weight, accepted is best, failed/escalated are misses.
    assert set(_OUTCOME_WEIGHT) == set(FEEDBACK_OUTCOMES)
    assert _OUTCOME_WEIGHT["accepted"] == 1.0
    assert _OUTCOME_WEIGHT["failed"] == 0.0 and _OUTCOME_WEIGHT["escalated"] == 0.0
    assert _OUTCOME_WEIGHT["retried"] == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_get_quality_nests_and_scores_from_rows():
    # Fake the DB result: two dimensions for one model.
    rows = [
        SimpleNamespace(model_tag="gpt-5.6-terra", task_type="coding",
                        samples=140, score_frac=0.81, accept_rate=0.8, escalation_rate=0.1),
        SimpleNamespace(model_tag="gpt-5.6-terra", task_type="reasoning",
                        samples=50, score_frac=0.5, accept_rate=0.5, escalation_rate=0.3),
    ]
    session = MagicMock()
    session.execute = AsyncMock(return_value=rows)
    repo = FeedbackRepository.__new__(FeedbackRepository)
    repo.session = session

    q = await repo.get_quality_by_model()
    assert q["gpt-5.6-terra"]["coding"] == {
        "score": 81.0, "samples": 140, "accept_rate": 0.8, "escalation_rate": 0.1,
    }
    assert q["gpt-5.6-terra"]["reasoning"]["score"] == 50.0


@pytest.mark.asyncio
async def test_feedback_endpoint_rejects_bad_outcome_but_accepts_valid():
    from mlpal_assistants_service.api.v2.feedback import FeedbackRequest, post_feedback
    from fastapi import HTTPException

    api_key = SimpleNamespace(user_id=1, id=2, has_permission=lambda p: p in ("messages", "chat"))
    session = MagicMock()

    # Bad outcome -> 400, nothing recorded.
    with pytest.raises(HTTPException) as ei:
        await post_feedback(
            FeedbackRequest(model="gpt-5.6-terra", task_type="coding", outcome="nope"),
            api_key, session,
        )
    assert ei.value.status_code == 400

    # Valid -> recorded; escalated_to dropped when outcome isn't 'escalated'.
    import mlpal_assistants_service.api.v2.feedback as fb
    rec = AsyncMock()
    fb.FeedbackRepository = MagicMock(return_value=SimpleNamespace(record=rec))
    resp = await post_feedback(
        FeedbackRequest(model="gpt-5.6-terra", task_type="coding",
                        outcome="accepted", escalated_to="claude-opus-4-8"),
        api_key, session,
    )
    assert resp.recorded is True
    assert rec.await_args.kwargs["escalated_to"] is None  # only kept for 'escalated'
    assert rec.await_args.kwargs["outcome"] == "accepted"
