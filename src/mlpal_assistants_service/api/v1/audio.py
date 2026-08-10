"""Audio API endpoints (TTS and transcription)."""

from fastapi import APIRouter, File, Form, Request, UploadFile, status
from fastapi.responses import Response

from mlpal_assistants_service.api.deps import (
    AudioServiceDep,
    CurrentAPIKey,
    RateLimitCheck,
)
from mlpal_assistants_service.schemas.audio import (
    TranscriptionRequest,
    TranscriptionResponse,
    TTSRequest,
    TTSResponse,
)

router = APIRouter()


@router.post(
    "/speech",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="Text to speech",
    description="Convert text to speech audio. Returns JSON with S3 URL by default, or raw audio bytes if Accept header includes audio/*.",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "url": "https://s3.../speech.mp3?...",
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
                    }
                },
                "audio/mpeg": {},
            },
            "description": "JSON with S3 URL (default) or raw audio bytes (Accept: audio/*)",
        }
    },
)
async def text_to_speech(
    body: TTSRequest,
    request: Request,
    api_key: CurrentAPIKey,
    _rate_limit: RateLimitCheck,
    audio_service: AudioServiceDep,
):
    """
    Convert text to speech audio.

    By default, returns JSON with a presigned S3 URL (like image generation).
    Set `Accept: audio/*` header to receive raw audio bytes instead.

    Voices available:
    - alloy, echo, fable, onyx, nova, shimmer

    Models available:
    - tts-1 (OpenAI - faster)
    - tts-1-hd (OpenAI - higher quality)
    """
    audio_bytes, tts_response = await audio_service.text_to_speech(
        user_id=api_key.user_id,
        api_key_id=api_key.id,
        request=body,
        model_policy=api_key.model_policy,
        budgets=api_key.budgets,
    )

    # Return raw bytes if client explicitly requests audio
    accept = request.headers.get("accept", "")
    if "audio/" in accept:
        return Response(
            content=audio_bytes,
            media_type=tts_response.content_type,
            headers={
                "X-Compute-Units": str(tts_response.cost.compute_units),
                "X-Latency-Ms": str(tts_response.cost.latency_ms),
            },
        )

    # Default: return JSON with S3 URL (consistent with images)
    return tts_response


@router.post(
    "/transcriptions",
    response_model=TranscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Transcribe audio",
    description="Transcribe audio to text.",
)
async def transcribe_audio(
    file: UploadFile = File(..., description="Audio file to transcribe"),
    model: str = Form(default="whisper-1", description="Transcription model"),
    language: str | None = Form(default=None, description="Language code (e.g., 'en')"),
    prompt: str | None = Form(default=None, description="Optional prompt for style"),
    api_key: CurrentAPIKey = None,  # type: ignore
    _rate_limit: RateLimitCheck = None,  # type: ignore
    audio_service: AudioServiceDep = None,  # type: ignore
) -> TranscriptionResponse:
    """
    Transcribe audio to text.

    Supports common audio formats:
    - mp3, mp4, mpeg, mpga, m4a, wav, webm

    Models available:
    - whisper-1 (OpenAI)
    """
    # Read file contents
    audio_data = await file.read()

    # Build request
    request = TranscriptionRequest(
        model=model,
        language=language,
        prompt=prompt,
    )

    return await audio_service.transcribe(
        user_id=api_key.user_id,
        api_key_id=api_key.id,
        audio_data=audio_data,
        filename=file.filename or "audio.mp3",
        request=request,
        model_policy=api_key.model_policy,
        budgets=api_key.budgets,
    )
