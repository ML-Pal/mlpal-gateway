"""Audio schemas (TTS and transcription)."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from mlpal_assistants_service.schemas.common import BaseSchema
from mlpal_assistants_service.schemas.routing import RoutingMetadata

# ============================================================================
# Text-to-Speech (TTS)
# ============================================================================


class TTSRequest(BaseSchema):
    """Request schema for text-to-speech."""

    input: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Text to convert to speech",
    )
    model: str = Field(
        default="tts-1",
        description="TTS model to use (tts-1 or tts-1-hd)",
    )
    voice: Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"] = Field(
        default="alloy",
        description="Voice to use for speech",
    )
    response_format: Literal["mp3", "opus", "aac", "flac", "wav"] = Field(
        default="mp3",
        description="Audio format for output",
    )
    speed: float = Field(
        default=1.0,
        ge=0.25,
        le=4.0,
        description="Playback speed (0.25 to 4.0)",
    )


class TTSCost(BaseSchema):
    """Cost information for TTS."""

    model_name: str = Field(..., description="Model used")
    provider: str = Field(..., description="Provider used")
    characters: int = Field(..., description="Characters processed")
    latency_ms: int = Field(..., description="Request latency in milliseconds")
    compute_units: float = Field(..., description="Compute units billed (provider pass-through, no markup)")


class TTSResponse(BaseSchema):
    """
    Response schema for TTS.

    When returned as JSON (via /v1/audio/speech endpoint with Accept: application/json),
    audio is stored in S3 and a presigned URL is returned.

    When returned as binary (default), audio bytes are streamed directly.

    When using MLPal meta-models (mlpal, mlpal-flash, mlpal-lite),
    the `routing` field contains information about which actual model was used.
    """

    url: str = Field(
        ...,
        description="Presigned URL to download the audio file. Valid for 1 hour.",
    )
    expires_at: datetime = Field(
        ...,
        description="UTC timestamp when the URL expires.",
    )
    content_type: str = Field(..., description="Audio MIME type")
    size_bytes: int = Field(..., ge=0, description="Audio file size in bytes")
    cost: TTSCost = Field(..., description="Cost information")
    routing: RoutingMetadata | None = Field(
        default=None,
        description="Routing metadata when using MLPal meta-models.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "url": "https://mlpal-assistants-assets.s3.us-east-2.amazonaws.com/generated/.../audio.mp3?...",
                "expires_at": "2026-01-27T11:30:00Z",
                "content_type": "audio/mpeg",
                "size_bytes": 102400,
                "cost": {
                    "model_name": "tts-1-hd",
                    "provider": "openai",
                    "characters": 500,
                    "latency_ms": 1200,
                    "compute_units": 0.015,
                },
                "routing": None,
            }
        }
    }


# ============================================================================
# Speech-to-Text (Transcription)
# ============================================================================


class TranscriptionRequest(BaseSchema):
    """Request schema for audio transcription."""

    model: str = Field(
        default="whisper-1",
        description="Transcription model to use",
    )
    language: str | None = Field(
        default=None,
        description="Language code (e.g., 'en', 'es') for better accuracy",
    )
    prompt: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional prompt to guide transcription style",
    )
    response_format: Literal["json", "text", "verbose_json"] = Field(
        default="json",
        description="Response format",
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Sampling temperature (0-1)",
    )


class TranscriptionCost(BaseSchema):
    """Cost information for transcription."""

    model_name: str = Field(..., description="Model used")
    provider: str = Field(..., description="Provider used")
    duration_seconds: float = Field(..., description="Audio duration in seconds")
    latency_ms: int = Field(..., description="Request latency in milliseconds")
    compute_units: float = Field(..., description="Compute units billed (provider pass-through, no markup)")


class TranscriptionResponse(BaseSchema):
    """Response schema for transcription."""

    text: str = Field(..., description="Transcribed text")
    language: str | None = Field(default=None, description="Detected language")
    duration: float | None = Field(default=None, description="Audio duration in seconds")
    cost: TranscriptionCost = Field(..., description="Cost information")
    routing: RoutingMetadata | None = Field(
        default=None,
        description="Routing metadata when using MLPal meta-models.",
    )
