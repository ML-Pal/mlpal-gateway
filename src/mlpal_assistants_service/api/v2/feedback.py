"""POST /v2/feedback — report a delegation outcome.

A coding harness delegates subtasks to models through the gateway; each outcome
(accepted / retried / escalated / failed) is real quality data. This ingests it
into model_feedback, where it's aggregated into the measured per-model quality
that ranks the catalog (see services/catalog.py + FeedbackRepository).

Deliberately lenient: unknown model tags or task types are stored as-is (the
aggregation only surfaces served models × the catalog's dimensions), and the
endpoint never fails the caller's real work — a bad feedback post 400s locally
but is never in the request hot path.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from mlpal_assistants_service.api.deps import CurrentAPIKey, SessionDep
from mlpal_assistants_service.api.v2.messages import _require_messages_scope
from mlpal_assistants_service.db.models import FEEDBACK_OUTCOMES
from mlpal_assistants_service.repositories.feedback_repository import FeedbackRepository

logger = logging.getLogger(__name__)

router = APIRouter()


class FeedbackRequest(BaseModel):
    model: str = Field(..., description="The model the subtask was delegated to")
    task_type: str = Field(..., description="Task dimension, e.g. 'coding', 'reasoning', 'tool_use'")
    outcome: str = Field(..., description=f"One of {FEEDBACK_OUTCOMES}")
    escalated_to: str | None = Field(default=None, description="On 'escalated', the model that succeeded instead")
    trace_id: str | None = Field(default=None, description="Optional link to the originating request")


class FeedbackResponse(BaseModel):
    recorded: bool


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Report a delegation outcome (feeds measured catalog rankings)",
)
async def post_feedback(
    body: FeedbackRequest,
    api_key: CurrentAPIKey,
    session: SessionDep,
) -> FeedbackResponse:
    _require_messages_scope(api_key)

    if body.outcome not in FEEDBACK_OUTCOMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"outcome must be one of {list(FEEDBACK_OUTCOMES)}",
        )
    # escalated_to is only meaningful for an escalation; ignore it otherwise
    # rather than rejecting (keeps the caller's reporting simple).
    escalated_to = body.escalated_to if body.outcome == "escalated" else None

    await FeedbackRepository(session).record(
        model_tag=body.model,
        task_type=body.task_type,
        outcome=body.outcome,
        user_id=getattr(api_key, "user_id", None),
        api_key_id=getattr(api_key, "id", None),
        escalated_to=escalated_to,
        trace_id=body.trace_id,
    )
    logger.info(
        f"[v2.feedback] model={body.model} task={body.task_type} "
        f"outcome={body.outcome} escalated_to={escalated_to}"
    )
    return FeedbackResponse(recorded=True)
