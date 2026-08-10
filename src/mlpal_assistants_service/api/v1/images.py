"""Image generation API endpoint."""

from fastapi import APIRouter, status

from mlpal_assistants_service.api.deps import (
    CurrentAPIKey,
    ImageServiceDep,
    RateLimitCheck,
)
from mlpal_assistants_service.schemas.images import (
    ImageGenerationRequest,
    ImageGenerationResponse,
)

router = APIRouter()


@router.post(
    "/generations",
    response_model=ImageGenerationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate images",
    description="Generate images from a text prompt.",
)
async def generate_images(
    body: ImageGenerationRequest,
    api_key: CurrentAPIKey,
    _rate_limit: RateLimitCheck,
    image_service: ImageServiceDep,
) -> ImageGenerationResponse:
    """
    Generate images from a text description.

    Supports:
    - Multiple images (1-4)
    - Different sizes (square, landscape, portrait)
    - Quality levels (standard, hd)

    Models available:
    - dall-e-3 (OpenAI)
    - dall-e-2 (OpenAI)
    """
    return await image_service.generate(
        user_id=api_key.user_id,
        api_key_id=api_key.id,
        request=body,
        model_policy=api_key.model_policy,
        budgets=api_key.budgets,
    )
