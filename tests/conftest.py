"""Pytest configuration and fixtures."""

import os

# Deterministic test environment: dummy provider keys BEFORE any settings
# import, so the suite passes identically in a fresh checkout with no .env
# (the OSS repo ships no keys) and never depends on the developer's real env.
for _k, _v in {
    "OPENAI_API_KEY": "sk-test-dummy",
    "ANTHROPIC_API_KEY": "sk-ant-test-dummy",
    "GOOGLE_API_KEY": "AIza-test-dummy",
}.items():
    os.environ.setdefault(_k, _v)

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mlpal_assistants_service.core.config import Settings
from mlpal_assistants_service.db.models import Base


# Test settings with in-memory SQLite
@pytest.fixture
def settings() -> Settings:
    """Test settings."""
    return Settings(
        environment="development",
        debug=True,
        ASSISTANTS_DB_HOST="localhost",
        ASSISTANTS_DB_USER="test",
        ASSISTANTS_DB_PASSWORD="test",
        ASSISTANTS_DB_NAME="test",
        OPENAI_API_KEY="test-openai-key",
        ANTHROPIC_API_KEY="test-anthropic-key",
        GOOGLE_API_KEY="test-google-key",
    )


@pytest.fixture
def mock_redis() -> MagicMock:
    """Mock Redis client."""
    redis_mock = MagicMock()
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.set = AsyncMock(return_value=True)
    redis_mock.setex = AsyncMock(return_value=True)
    redis_mock.incrbyfloat = AsyncMock(return_value=1.0)
    redis_mock.expire = AsyncMock(return_value=True)
    redis_mock.zadd = AsyncMock(return_value=1)
    redis_mock.zcard = AsyncMock(return_value=0)
    redis_mock.zremrangebyscore = AsyncMock(return_value=0)
    redis_mock.zrange = AsyncMock(return_value=[])
    redis_mock.ping = AsyncMock(return_value=True)
    redis_mock.close = AsyncMock()
    return redis_mock


@pytest_asyncio.fixture
async def async_session() -> AsyncGenerator[AsyncSession, None]:
    """Create an async session for testing with SQLite."""
    # Use in-memory SQLite for tests
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def mock_openai_adapter() -> MagicMock:
    """Mock OpenAI adapter."""
    from mlpal_assistants_service.adapters.base import AdapterResponse

    adapter = MagicMock()
    adapter.provider_name = "openai"
    adapter.chat = AsyncMock(
        return_value=AdapterResponse(
            content="Test response",
            input_tokens=10,
            output_tokens=20,
            finish_reason="stop",
            model="gpt-5.2",
        )
    )
    adapter.health_check = AsyncMock(return_value=True)
    return adapter


@pytest.fixture
def mock_anthropic_adapter() -> MagicMock:
    """Mock Anthropic adapter."""
    from mlpal_assistants_service.adapters.base import AdapterResponse

    adapter = MagicMock()
    adapter.provider_name = "anthropic"
    adapter.chat = AsyncMock(
        return_value=AdapterResponse(
            content="Test response from Claude",
            input_tokens=15,
            output_tokens=25,
            finish_reason="end_turn",
            model="claude-opus-4.5",
        )
    )
    adapter.health_check = AsyncMock(return_value=True)
    return adapter


@pytest_asyncio.fixture
async def app(
    mock_redis: MagicMock,
    mock_openai_adapter: MagicMock,
    mock_anthropic_adapter: MagicMock,
) -> AsyncGenerator[FastAPI, None]:
    """Create test FastAPI application."""
    from mlpal_assistants_service.main import app as main_app

    # Override app state
    main_app.state.redis = mock_redis
    main_app.state.adapters = {
        "openai": mock_openai_adapter,
        "anthropic": mock_anthropic_adapter,
    }

    yield main_app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Create async HTTP client for testing."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# Helper fixtures
@pytest.fixture
def sample_api_key() -> str:
    """Sample API key for testing."""
    return "mlpal_sk_" + "a" * 64


@pytest.fixture
def sample_messages() -> list[dict[str, Any]]:
    """Sample chat messages for testing."""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, how are you?"},
    ]
