"""Repository for APIKey access."""

from datetime import datetime, timezone

from sqlalchemy import select

from mlpal_assistants_service.db.models import APIKey
from mlpal_assistants_service.repositories.base import BaseRepository


class APIKeyRepository(BaseRepository[APIKey]):
    """Repository for API key operations."""

    model = APIKey

    async def get_by_hash(self, key_hash: str) -> APIKey | None:
        """Get an API key by its hash."""
        return await self.get_one(key_hash=key_hash)

    async def get_valid_by_hash(self, key_hash: str) -> APIKey | None:
        """Get a valid (active, not expired, not revoked) API key by hash."""
        stmt = (
            select(APIKey)
            .where(
                APIKey.key_hash == key_hash,
                APIKey.is_active == True,  # noqa: E712
                APIKey.revoked_at.is_(None),
            )
        )

        result = await self.session.execute(stmt)
        api_key = result.scalar_one_or_none()

        if not api_key:
            return None

        # Check expiration
        if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
            return None

        return api_key

    async def get_user_keys(
        self,
        user_id: int,
        include_revoked: bool = False,
    ) -> list[APIKey]:
        """Get all API keys for a user."""
        stmt = select(APIKey).where(APIKey.user_id == user_id)

        if not include_revoked:
            stmt = stmt.where(
                APIKey.is_active == True,  # noqa: E712
                APIKey.revoked_at.is_(None),
            )

        stmt = stmt.order_by(APIKey.created_at.desc())

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_key(
        self,
        user_id: int,
        key_hash: str,
        key_prefix: str,
        name: str,
        description: str | None = None,
        permissions: dict | None = None,
        rate_limit_tier: str = "standard",
        expires_at: datetime | None = None,
    ) -> APIKey:
        """Create a new API key."""
        return await self.create(
            user_id=user_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=name,
            description=description,
            permissions=permissions or {"*": True},
            rate_limit_tier=rate_limit_tier,
            expires_at=expires_at,
        )

    async def revoke(self, key_id: int) -> APIKey | None:
        """Revoke an API key."""
        api_key = await self.get_by_id(key_id)
        if not api_key:
            return None

        api_key.is_active = False
        api_key.revoked_at = datetime.now(timezone.utc)
        await self.session.flush()
        return api_key

    async def revoke_by_hash(self, key_hash: str) -> APIKey | None:
        """Revoke an API key by its hash."""
        api_key = await self.get_by_hash(key_hash)
        if not api_key:
            return None

        api_key.is_active = False
        api_key.revoked_at = datetime.now(timezone.utc)
        await self.session.flush()
        return api_key

    async def update_last_used(self, key_id: int) -> None:
        """Update the last_used_at timestamp for an API key."""
        api_key = await self.get_by_id(key_id)
        if api_key:
            api_key.last_used_at = datetime.now(timezone.utc)
            await self.session.flush()

    async def update_permissions(
        self,
        key_id: int,
        permissions: dict,
    ) -> APIKey | None:
        """Update permissions for an API key."""
        api_key = await self.get_by_id(key_id)
        if not api_key:
            return None

        api_key.permissions = permissions
        await self.session.flush()
        return api_key

    async def update_rate_limit_tier(
        self,
        key_id: int,
        tier: str,
    ) -> APIKey | None:
        """Update rate limit tier for an API key."""
        api_key = await self.get_by_id(key_id)
        if not api_key:
            return None

        api_key.rate_limit_tier = tier
        await self.session.flush()
        return api_key

    async def count_active_keys(self, user_id: int) -> int:
        """Count active API keys for a user."""
        return await self.count(
            user_id=user_id,
            is_active=True,
        )
