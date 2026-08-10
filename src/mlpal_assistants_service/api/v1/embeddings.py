"""Embeddings API endpoint."""

from fastapi import APIRouter, status

from mlpal_assistants_service.api.deps import (
    CurrentAPIKey,
    EmbeddingServiceDep,
    RateLimitCheck,
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
    _rate_limit: RateLimitCheck,
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
    return await embedding_service.embed(
        user_id=api_key.user_id,
        api_key_id=api_key.id,
        request=body,
        model_policy=api_key.model_policy,
        budgets=api_key.budgets,
    )
