"""Repository for ModelRegistry access."""

from sqlalchemy import select

from mlpal_assistants_service.db.models import ModelRegistry
from mlpal_assistants_service.repositories.base import BaseRepository


class ModelRepository(BaseRepository[ModelRegistry]):
    """Repository for model registry operations."""

    model = ModelRegistry

    async def get_by_tag(self, model_tag: str) -> ModelRegistry | None:
        """Get a model by its tag."""
        return await self.get_one(model_tag=model_tag)

    async def get_active_models(
        self,
        provider: str | None = None,
        operation: str | None = None,
    ) -> list[ModelRegistry]:
        """Get all active (non-deprecated) models."""
        stmt = select(ModelRegistry).where(
            ModelRegistry.is_active == True,  # noqa: E712
            ModelRegistry.is_deprecated == False,  # noqa: E712
        )

        if provider:
            stmt = stmt.where(ModelRegistry.provider == provider)

        if operation:
            stmt = stmt.where(
                ModelRegistry.capabilities["operation"].astext == operation
            )

        stmt = stmt.order_by(ModelRegistry.priority, ModelRegistry.model_tag)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_provider(self, provider: str) -> list[ModelRegistry]:
        """Get all models for a provider."""
        return await self.get_all(provider=provider, is_active=True)

    async def get_by_operation(self, operation: str) -> list[ModelRegistry]:
        """Get all models supporting an operation (chat, embedding, etc.)."""
        stmt = (
            select(ModelRegistry)
            .where(
                ModelRegistry.is_active == True,  # noqa: E712
                ModelRegistry.capabilities["operation"].astext == operation,
            )
            .order_by(ModelRegistry.priority, ModelRegistry.model_tag)
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_chat_models(self) -> list[ModelRegistry]:
        """Get all active chat models."""
        return await self.get_by_operation("chat")

    async def get_embedding_models(self) -> list[ModelRegistry]:
        """Get all active embedding models."""
        return await self.get_by_operation("embedding")

    async def get_image_models(self) -> list[ModelRegistry]:
        """Get all active image generation models."""
        return await self.get_by_operation("image_generation")

    async def get_with_fallback(self, model_tag: str) -> tuple[ModelRegistry | None, ModelRegistry | None]:
        """Get a model and its fallback model if configured."""
        model = await self.get_by_tag(model_tag)
        if not model:
            return None, None

        fallback = None
        if model.fallback_model_tag:
            fallback = await self.get_by_tag(model.fallback_model_tag)

        return model, fallback

    async def set_deprecated(
        self,
        model_tag: str,
        message: str | None = None,
    ) -> ModelRegistry | None:
        """Mark a model as deprecated."""
        model = await self.get_by_tag(model_tag)
        if not model:
            return None

        model.is_deprecated = True
        model.deprecation_message = message
        await self.session.flush()
        return model
