"""Embeddings API endpoint."""

from fastapi import APIRouter, HTTPException, status

from mlpal_assistants_service.api.deps import (
    CurrentAPIKey,
    EmbeddingServiceDep,
)
from mlpal_assistants_service.schemas.embeddings import (
    EmbeddingRequest,
    EmbeddingResponse,
)

router = APIRouter()


@router.post(
    "",
    response_model=EmbeddingResponse,
    status_code=status.HTTP_200_OK,
    summary="Create embeddings",
    description="Generate embeddings for text input(s).",
)
async def create_embeddings(
    body: EmbeddingRequest,
    api_key: CurrentAPIKey,
    embedding_service: EmbeddingServiceDep,
) -> EmbeddingResponse:
    """
    Generate embeddings for the provided text(s).

    Supports:
    - Single text string
    - List of text strings (batch)

    Models available:
    - text-embedding-3-large (OpenAI)
    - text-embedding-3-small (OpenAI)
    - text-embedding-004 (Google)
    """
    # Permission gate — same contract as /v1/chat: a key scoped away from this
    # surface must not be able to spend on it.
    # "embed" is a legacy singular some existing keys carry — accept both.
    if not (api_key.has_permission("embeddings") or api_key.has_permission("embed")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key does not have permission for embeddings",
        )
    return await embedding_service.embed(
        user_id=api_key.user_id,
        api_key_id=api_key.id,
        request=body,
        model_policy=api_key.model_policy,
        budgets=api_key.budgets,
    )
