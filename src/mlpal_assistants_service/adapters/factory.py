"""Factory for creating provider adapters.

The AdapterFactory provides a centralized way to create and manage
provider adapters, supporting:
- Lazy initialization (adapters created on first use)
- Singleton pattern (one adapter instance per provider)
- Runtime registration of new adapters
- Configuration-based provider enabling/disabling
"""

import logging
from typing import TYPE_CHECKING

from mlpal_assistants_service.core.config import get_settings

if TYPE_CHECKING:
    from mlpal_assistants_service.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)


class AdapterFactory:
    """
    Factory for creating and managing provider adapters.

    Usage:
        factory = AdapterFactory()

        # Get adapter (created on first access)
        openai_adapter = factory.get("openai")

        # Get all enabled adapters
        adapters = factory.get_all()

        # Check if provider is available
        if factory.is_available("anthropic"):
            adapter = factory.get("anthropic")
    """

    # Registry of adapter classes (provider name -> class)
    _adapter_classes: dict[str, type["BaseAdapter"]] = {}

    # Singleton instances (provider name -> instance)
    _instances: dict[str, "BaseAdapter"] = {}

    def __init__(self) -> None:
        """Initialize the factory with default adapters."""
        self._register_default_adapters()

    def _register_default_adapters(self) -> None:
        """Register all built-in adapter classes."""
        # Import here to avoid circular imports
        from mlpal_assistants_service.adapters.anthropic import AnthropicAdapter
        from mlpal_assistants_service.adapters.bedrock import BedrockAdapter
        from mlpal_assistants_service.adapters.google import GoogleAdapter
        from mlpal_assistants_service.adapters.openai import OpenAIAdapter

        self._adapter_classes = {
            "openai": OpenAIAdapter,
            "anthropic": AnthropicAdapter,
            "google": GoogleAdapter,
            "bedrock": BedrockAdapter,
        }

    @classmethod
    def register(cls, provider: str, adapter_class: type["BaseAdapter"]) -> None:
        """
        Register a new adapter class.

        Args:
            provider: Provider name (e.g., "openai", "anthropic")
            adapter_class: Adapter class (must extend BaseAdapter)

        Example:
            AdapterFactory.register("custom", CustomAdapter)
        """
        cls._adapter_classes[provider] = adapter_class
        logger.info(f"Registered adapter for provider: {provider}")

    def get(self, provider: str) -> "BaseAdapter":
        """
        Get an adapter instance for a provider.

        Creates the adapter on first access (lazy initialization).
        Returns cached instance on subsequent calls.

        Args:
            provider: Provider name (e.g., "openai", "anthropic")

        Returns:
            Adapter instance

        Raises:
            ValueError: If provider is not registered
            RuntimeError: If adapter fails to initialize
        """
        # Return cached instance if exists
        if provider in self._instances:
            return self._instances[provider]

        # Get adapter class
        adapter_class = self._adapter_classes.get(provider)
        if not adapter_class:
            available = ", ".join(sorted(self._adapter_classes.keys()))
            raise ValueError(
                f"Unknown provider: '{provider}'. "
                f"Available providers: {available}"
            )

        # Create instance
        try:
            instance = adapter_class()
            self._instances[provider] = instance
            logger.info(f"Created adapter instance for provider: {provider}")
            return instance
        except Exception as e:
            logger.error(f"Failed to create adapter for {provider}: {e}")
            raise RuntimeError(f"Failed to initialize {provider} adapter: {e}") from e

    def get_all(self) -> dict[str, "BaseAdapter"]:
        """
        Get all adapter instances.

        Creates adapters that haven't been initialized yet.

        Returns:
            Dict mapping provider names to adapter instances
        """
        for provider in self._adapter_classes:
            if provider not in self._instances:
                try:
                    self.get(provider)
                except Exception as e:
                    logger.warning(f"Could not initialize {provider} adapter: {e}")

        return dict(self._instances)

    def get_enabled(self) -> dict[str, "BaseAdapter"]:
        """
        Get only adapters that have valid API credentials configured.

        Returns:
            Dict of provider name -> adapter for providers with valid config
        """
        settings = get_settings()
        enabled = {}

        # Check each provider's API key
        provider_keys = {
            "openai": settings.openai_api_key,
            "anthropic": settings.anthropic_api_key,
            "google": settings.google_api_key,
            "bedrock": settings.enable_bedrock,
        }

        for provider, has_key in provider_keys.items():
            if has_key and provider in self._adapter_classes:
                try:
                    enabled[provider] = self.get(provider)
                except Exception as e:
                    logger.warning(f"Could not enable {provider}: {e}")

        return enabled

    def is_available(self, provider: str) -> bool:
        """
        Check if a provider is registered and can be initialized.

        Args:
            provider: Provider name

        Returns:
            True if provider is available
        """
        return provider in self._adapter_classes

    def is_enabled(self, provider: str) -> bool:
        """
        Check if a provider has valid configuration.

        Args:
            provider: Provider name

        Returns:
            True if provider is configured and enabled
        """
        settings = get_settings()

        provider_keys = {
            "openai": settings.openai_api_key,
            "anthropic": settings.anthropic_api_key,
            "google": settings.google_api_key,
            "bedrock": settings.enable_bedrock,
        }

        return bool(provider_keys.get(provider))

    @property
    def providers(self) -> list[str]:
        """Get list of all registered provider names."""
        return list(self._adapter_classes.keys())

    @property
    def enabled_providers(self) -> list[str]:
        """Get list of providers with valid configuration."""
        return [p for p in self.providers if self.is_enabled(p)]

    def clear_instances(self) -> None:
        """Clear all cached adapter instances (for testing)."""
        self._instances.clear()


# Singleton factory instance
_factory: AdapterFactory | None = None


def get_adapter_factory() -> AdapterFactory:
    """Get the singleton AdapterFactory instance."""
    global _factory
    if _factory is None:
        _factory = AdapterFactory()
    return _factory


def get_adapter(provider: str) -> "BaseAdapter":
    """
    Convenience function to get an adapter.

    Args:
        provider: Provider name

    Returns:
        Adapter instance
    """
    return get_adapter_factory().get(provider)
