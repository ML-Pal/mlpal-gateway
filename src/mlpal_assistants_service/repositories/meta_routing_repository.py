"""Repository for MetaModelRouting access."""

from sqlalchemy import select

from mlpal_assistants_service.db.models import MetaModelRouting
from mlpal_assistants_service.repositories.base import BaseRepository


class MetaRoutingRepository(BaseRepository[MetaModelRouting]):
    """Repository for meta-model routing operations."""

    model = MetaModelRouting

    async def get_routing(
        self,
        meta_model_tag: str,
        operation: str,
    ) -> MetaModelRouting | None:
        """First (highest-priority) routing rule — availability-blind. Prefer
        get_candidates + a served-check for actual resolution."""
        rows = await self.get_candidates(meta_model_tag, operation)
        return rows[0] if rows else None

    async def get_candidates(
        self,
        meta_model_tag: str,
        operation: str,
    ) -> list[MetaModelRouting]:
        """ALL active candidates for (tag, operation), priority-ordered. The
        resolver walks these and picks the first one this deployment serves."""
        stmt = (
            select(MetaModelRouting)
            .where(
                MetaModelRouting.meta_model_tag == meta_model_tag,
                MetaModelRouting.operation == operation,
                MetaModelRouting.is_active == True,  # noqa: E712
            )
            .order_by(MetaModelRouting.priority)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_routings_for_model(
        self,
        meta_model_tag: str,
    ) -> list[MetaModelRouting]:
        """Get all routing rules for a meta-model."""
        stmt = (
            select(MetaModelRouting)
            .where(
                MetaModelRouting.meta_model_tag == meta_model_tag,
                MetaModelRouting.is_active == True,  # noqa: E712
            )
            .order_by(MetaModelRouting.operation, MetaModelRouting.priority)
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_fallback_routings(
        self,
        meta_model_tag: str,
        operation: str,
    ) -> list[MetaModelRouting]:
        """
        Get all routing rules for fallback ordering.

        Returns all active routings ordered by priority.
        Priority 0 is primary, higher numbers are fallbacks.
        """
        stmt = (
            select(MetaModelRouting)
            .where(
                MetaModelRouting.meta_model_tag == meta_model_tag,
                MetaModelRouting.operation == operation,
                MetaModelRouting.is_active == True,  # noqa: E712
            )
            .order_by(MetaModelRouting.priority)
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_meta_models(self) -> list[str]:
        """Get all unique meta-model tags."""
        stmt = (
            select(MetaModelRouting.meta_model_tag)
            .where(MetaModelRouting.is_active == True)  # noqa: E712
            .distinct()
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_operations_for_model(
        self,
        meta_model_tag: str,
    ) -> list[str]:
        """Get all operations supported by a meta-model."""
        stmt = (
            select(MetaModelRouting.operation)
            .where(
                MetaModelRouting.meta_model_tag == meta_model_tag,
                MetaModelRouting.is_active == True,  # noqa: E712
            )
            .distinct()
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())
