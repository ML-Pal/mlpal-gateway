"""
Asset schemas for generated content (images, audio).

These schemas represent AI-generated assets stored temporarily in S3.
URLs are presigned and expire after a configurable TTL (default 1 hour).
"""

from datetime import datetime

from pydantic import Field

from mlpal_assistants_service.schemas.common import BaseSchema


class GeneratedAsset(BaseSchema):
    """
    A generated asset with temporary presigned URL.

    Like OpenAI and other production APIs, generated content is stored
    temporarily and made available via presigned URLs that expire.

    Users are responsible for downloading files before expiration.

    Attributes:
        url: Presigned S3 URL for downloading the asset
        expires_at: UTC timestamp when the URL stops working
        content_type: MIME type of the asset
        size_bytes: File size in bytes
    """

    url: str = Field(
        ...,
        description="Presigned URL to download the asset. Expires after the time shown in expires_at.",
    )
    expires_at: datetime = Field(
        ...,
        description="UTC timestamp when the URL expires. Download before this time.",
    )
    content_type: str = Field(
        ...,
        description="MIME type of the asset (e.g., 'image/png', 'audio/mpeg')",
    )
    size_bytes: int = Field(
        ...,
        ge=0,
        description="File size in bytes",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "url": "https://mlpal-assistants-assets.s3.us-east-2.amazonaws.com/generated/123/abc-def/uuid_image.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&...",
                "expires_at": "2026-01-27T11:30:00Z",
                "content_type": "image/png",
                "size_bytes": 524288,
            }
        }
    }
