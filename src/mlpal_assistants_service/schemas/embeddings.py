"""Embedding schemas."""

from pydantic import Field

from mlpal_assistants_service.schemas.common import BaseSchema
from mlpal_assistants_service.schemas.routing import RoutingMetadata


class EmbeddingRequest(BaseSchema):
    """Request schema for generating embeddings."""

    input: list[str] | str = Field(
        ...,
        description="Text(s) to embed. Can be a single string or list of strings.",
    )
    model: str = Field(
        default="text-embedding-3-large",
        description="Embedding model to use",
    )
    dimensions: int | None = Field(
        default=None,
        gt=0,
        description="Output dimensions (for models that support it)",
    )


class EmbeddingData(BaseSchema):
    """Single embedding result."""

    index: int = Field(..., description="Index of the input text")
    embedding: list[float] = Field(..., description="Embedding vector")


class EmbeddingUsage(BaseSchema):
    """Token usage for embeddings."""

    prompt_tokens: int = Field(..., description="Number of input tokens")
    total_tokens: int = Field(..., description="Total tokens used")


class EmbeddingCost(BaseSchema):
    """Cost information for embeddings."""

    model_name: str = Field(..., description="Model used")
    provider: str = Field(..., description="Provider used")
    tokens: int = Field(..., description="Total tokens processed")
    latency_ms: int = Field(..., description="Request latency in milliseconds")
    compute_units: float = Field(..., description="Compute units billed (provider pass-through, no markup)")


class EmbeddingResponse(BaseSchema):
    """Response schema for embeddings."""

    data: list[EmbeddingData] = Field(..., description="List of embeddings")
    model: str = Field(..., description="Model used")
    usage: EmbeddingUsage = Field(..., description="Token usage")
    cost: EmbeddingCost = Field(..., description="Cost information")
    routing: RoutingMetadata | None = Field(
        default=None,
        description="Routing metadata when using MLPal meta-models.",
    )
