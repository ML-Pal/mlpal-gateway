"""Unhandled errors must be logged and JWT-auth DB failures must be 503s.

Regression tests for the 2026-07-21 /v1/keys incident: five 500s reached
clients with zero log lines — undiagnosable after the fact.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from mlpal_assistants_service.api.deps import get_current_user_from_jwt
from mlpal_assistants_service.core.auth import JWTUser


@pytest.mark.asyncio
async def test_unhandled_exception_returns_500_and_logs():
    """A route that raises must produce a structured 500 AND a log record."""
    from mlpal_assistants_service.main import app

    @app.get("/boom-test-route")
    async def boom():
        raise RuntimeError("kaboom")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    with patch("mlpal_assistants_service.main.logger") as mock_logger:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/boom-test-route")

    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "InternalServerError"
    # The message must be opaque — no leaked internals.
    assert "kaboom" not in resp.text

    assert mock_logger.error.called
    call = mock_logger.error.call_args
    assert call.args[0] == "Unhandled exception"
    assert call.kwargs["path"] == "/boom-test-route"
    assert isinstance(call.kwargs["exc_info"], RuntimeError)


class TestJWTAuthDBFailure:
    def _mock_validator(self):
        validator = MagicMock()
        validator.validate_token.return_value = {"sub": "abc", "token_use": "access"}
        validator.extract_user.return_value = JWTUser(
            cognito_sub="abc", email=None, first_name=None, last_name=None
        )
        return validator

    @pytest.mark.asyncio
    async def test_db_error_becomes_503_not_500(self):
        session = MagicMock()
        session.execute = AsyncMock(
            side_effect=OperationalError("SELECT 1", {}, Exception("conn reset"))
        )
        settings = MagicMock(user_schema="users")

        with (
            patch(
                "mlpal_assistants_service.api.deps.get_cognito_validator",
                return_value=self._mock_validator(),
            ),
            patch("mlpal_assistants_service.api.deps.logger") as mock_logger,
        ):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                await get_current_user_from_jwt(
                    authorization="Bearer sometoken",
                    session=session,
                    settings=settings,
                )

        assert exc_info.value.status_code == 503
        assert mock_logger.error.called
        assert mock_logger.error.call_args.args[0] == "User lookup failed during JWT auth"

    @pytest.mark.asyncio
    async def test_unknown_user_is_still_401(self):
        result = MagicMock()
        result.fetchone.return_value = None
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)
        settings = MagicMock(user_schema="users")

        with patch(
            "mlpal_assistants_service.api.deps.get_cognito_validator",
            return_value=self._mock_validator(),
        ):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                await get_current_user_from_jwt(
                    authorization="Bearer sometoken",
                    session=session,
                    settings=settings,
                )

        assert exc_info.value.status_code == 401
