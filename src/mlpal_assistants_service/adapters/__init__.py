"""Provider adapters for AI model APIs."""

from mlpal_assistants_service.adapters.anthropic import AnthropicAdapter
from mlpal_assistants_service.adapters.base import AdapterResponse, BaseAdapter
from mlpal_assistants_service.adapters.bedrock import BedrockAdapter
from mlpal_assistants_service.adapters.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpen,
    CircuitBreakerRegistry,
    CircuitState,
)
from mlpal_assistants_service.adapters.factory import (
    AdapterFactory,
    get_adapter,
    get_adapter_factory,
)
from mlpal_assistants_service.adapters.google import GoogleAdapter
from mlpal_assistants_service.adapters.openai import OpenAIAdapter

__all__ = [
    # Base
    "BaseAdapter",
    "AdapterResponse",
    # Adapters
    "OpenAIAdapter",
    "AnthropicAdapter",
    "GoogleAdapter",
    "BedrockAdapter",
    # Factory
    "AdapterFactory",
    "get_adapter",
    "get_adapter_factory",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerOpen",
    "CircuitBreakerRegistry",
    "CircuitState",
]
