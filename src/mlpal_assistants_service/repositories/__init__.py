"""Repository layer for data access abstraction.

Repositories provide a clean interface for database operations,
abstracting away SQLAlchemy details from the service layer.

Usage:
    from mlpal_assistants_service.repositories import ModelRepository, PricingRepository

    async def get_model_pricing(session: AsyncSession, model_tag: str):
        model_repo = ModelRepository(session)
        pricing_repo = PricingRepository(session)

        model = await model_repo.get_by_tag(model_tag)
        pricing = await pricing_repo.get_current_pricing(model_tag, "chat")

        return model, pricing
"""

from mlpal_assistants_service.repositories.api_key_repository import APIKeyRepository
from mlpal_assistants_service.repositories.base import BaseRepository
from mlpal_assistants_service.repositories.billing_repository import BillingRepository
from mlpal_assistants_service.repositories.credit_repository import CreditRepository
from mlpal_assistants_service.repositories.meta_routing_repository import MetaRoutingRepository
from mlpal_assistants_service.repositories.model_repository import ModelRepository
from mlpal_assistants_service.repositories.pricing_repository import PricingRepository
from mlpal_assistants_service.repositories.usage_repository import UsageRepository

__all__ = [
    "BaseRepository",
    "APIKeyRepository",
    "BillingRepository",
    "CreditRepository",
    "MetaRoutingRepository",
    "ModelRepository",
    "PricingRepository",
    "UsageRepository",
]
