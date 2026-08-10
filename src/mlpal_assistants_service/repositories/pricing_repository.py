"""Repository for ModelPricing access."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from mlpal_assistants_service.db.models import ModelPricing
from mlpal_assistants_service.repositories.base import BaseRepository


class PricingRepository(BaseRepository[ModelPricing]):
    """Repository for model pricing operations."""

    model = ModelPricing

    async def get_current_pricing(
        self,
        model_tag: str,
        operation: str,
        as_of_date: date | None = None,
    ) -> ModelPricing | None:
        """
        Get the current pricing for a model and operation.

        Returns the most recent pricing that is effective as of the given date.
        """
        if as_of_date is None:
            as_of_date = date.today()

        stmt = (
            select(ModelPricing)
            .where(
                ModelPricing.model_tag == model_tag,
                ModelPricing.operation == operation,
                ModelPricing.is_active == True,  # noqa: E712
                ModelPricing.effective_date <= as_of_date,
            )
            .order_by(ModelPricing.effective_date.desc())
            .limit(1)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_current_pricing(
        self,
        as_of_date: date | None = None,
    ) -> list[ModelPricing]:
        """Get current pricing for all models."""
        if as_of_date is None:
            as_of_date = date.today()

        # Subquery to get max effective_date per model_tag + operation
        from sqlalchemy import func

        subq = (
            select(
                ModelPricing.model_tag,
                ModelPricing.operation,
                func.max(ModelPricing.effective_date).label("max_date"),
            )
            .where(
                ModelPricing.is_active == True,  # noqa: E712
                ModelPricing.effective_date <= as_of_date,
            )
            .group_by(ModelPricing.model_tag, ModelPricing.operation)
            .subquery()
        )

        stmt = (
            select(ModelPricing)
            .join(
                subq,
                (ModelPricing.model_tag == subq.c.model_tag)
                & (ModelPricing.operation == subq.c.operation)
                & (ModelPricing.effective_date == subq.c.max_date),
            )
            .order_by(ModelPricing.model_tag, ModelPricing.operation)
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_pricing_by_tier(self, tier: str) -> list[ModelPricing]:
        """Get all pricing entries for a tier (economy, standard, premium)."""
        return await self.get_all(tier=tier, is_active=True)

    async def update_markup(
        self,
        model_tag: str,
        operation: str,
        markup_multiplier: Decimal,
    ) -> ModelPricing | None:
        """Update the markup multiplier for a model's pricing."""
        pricing = await self.get_current_pricing(model_tag, operation)
        if not pricing:
            return None

        pricing.markup_multiplier = markup_multiplier
        await self.session.flush()
        return pricing

    async def add_pricing(
        self,
        model_tag: str,
        operation: str,
        tier: str,
        input_rate: Decimal,
        output_rate: Decimal,
        rate_unit: str = "per_1m_tokens",
        markup_multiplier: Decimal = Decimal("3.0"),
        effective_date: date | None = None,
    ) -> ModelPricing:
        """Add new pricing (e.g., for price changes with new effective date)."""
        if effective_date is None:
            effective_date = date.today()

        return await self.create(
            model_tag=model_tag,
            operation=operation,
            tier=tier,
            input_rate=input_rate,
            output_rate=output_rate,
            rate_unit=rate_unit,
            markup_multiplier=markup_multiplier,
            effective_date=effective_date,
        )
