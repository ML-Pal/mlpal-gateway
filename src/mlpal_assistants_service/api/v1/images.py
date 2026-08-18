"""Image generation API endpoint."""

from fastapi import APIRouter, HTTPException, status

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
    # Permission gate — same contract as /v1/chat: a key scoped away from this
    # surface must not be able to spend on it.
    # "image" is a legacy singular some existing keys carry — accept both.
    if not (api_key.has_permission("images") or api_key.has_permission("image")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key does not have permission for image generation",
        )
    return await image_service.generate(
        user_id=api_key.user_id,
        api_key_id=api_key.id,
        request=body,
        model_policy=api_key.model_policy,
        budgets=api_key.budgets,
    )
