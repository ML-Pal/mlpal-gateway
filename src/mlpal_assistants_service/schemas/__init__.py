"""Pydantic schemas for request/response validation."""

from mlpal_assistants_service.schemas.api_key import (
    APIKeyCreate,
    APIKeyResponse,
    APIKeyWithSecret,
)
from mlpal_assistants_service.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    CostInfo,
)
from mlpal_assistants_service.schemas.common import (
    ErrorResponse,
    HealthResponse,
    PaginatedResponse,
)
from mlpal_assistants_service.schemas.model import ModelInfo, ModelListResponse
from mlpal_assistants_service.schemas.usage import UsageRecord, UsageSummary

__all__ = [
    # API Key
    "APIKeyCreate",
    "APIKeyResponse",
    "APIKeyWithSecret",
    # Chat
    "ChatMessage",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "CostInfo",
    # Common
    "ErrorResponse",
    "HealthResponse",
    "PaginatedResponse",
    # Model
    "ModelInfo",
    "ModelListResponse",
    # Usage
    "UsageRecord",
    "UsageSummary",
]
