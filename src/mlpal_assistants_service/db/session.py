"""Database session management with async SQLAlchemy."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from mlpal_assistants_service.core.config import get_settings

settings = get_settings()

# Create async engine with connection pooling
engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,  # Verify connections before use
    echo=settings.debug,  # Log SQL in debug mode
)


# Set search_path on connection checkout
@event.listens_for(engine.sync_engine, "connect")
def set_search_path(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
    """Set the search_path to use the assistants schema."""
    cursor = dbapi_connection.cursor()
    cursor.execute(f"SET search_path TO {settings.db_schema}, public")
    cursor.close()


# Session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that provides a database session.

    Usage:
        @router.get("/items")
        async def get_items(session: AsyncSession = Depends(get_session)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def session_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for database sessions.

    Usage:
        async with session_context() as session:
            result = await session.execute(...)
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_database_connection() -> bool:
    """Check if database is accessible."""
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
            return True
    except Exception:
        return False
