"""P0 #2 auth seam: management endpoints resolve the caller via `auth_backend`.
Local (OSS) uses an admin-scoped API key; managed delegates to the Cognito JWT
path unchanged. This is what lets a self-hosted box manage its own keys/policies
without Cognito or a users table."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from mlpal_assistants_service.api.deps import AuthenticatedUser, get_management_principal
from mlpal_assistants_service.core.exceptions import InvalidAPIKeyError

_LOCAL = SimpleNamespace(auth_backend="local")


def _key_service(api_key=None, invalid=False):
    svc = MagicMock()
    svc.validate_key = AsyncMock(
        side_effect=InvalidAPIKeyError("revoked") if invalid else None,
        return_value=api_key,
    )
    return svc


def _admin_key(user_id=42, is_admin=True):
    k = MagicMock()
    k.user_id = user_id
    k.has_permission = MagicMock(side_effect=lambda perm: perm == "admin" and is_admin)
    return k


@pytest.mark.asyncio
async def test_local_admin_key_resolves_to_principal():
    p = await get_management_principal("Bearer mlpal_sk_abc", _key_service(_admin_key(42)),
                                       MagicMock(), _LOCAL)
    assert isinstance(p, AuthenticatedUser) and p.id == 42  # keys created under admin's user_id


@pytest.mark.asyncio
async def test_local_non_admin_key_403():
    with pytest.raises(HTTPException) as ei:
        await get_management_principal("Bearer mlpal_sk_abc",
                                       _key_service(_admin_key(1, is_admin=False)),
                                       MagicMock(), _LOCAL)
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_local_missing_auth_401():
    with pytest.raises(HTTPException) as ei:
        await get_management_principal(None, _key_service(), MagicMock(), _LOCAL)
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_local_jwt_token_rejected_needs_admin_key():
    with pytest.raises(HTTPException) as ei:  # a JWT (non-key prefix) is not accepted in local mode
        await get_management_principal("Bearer eyJhbGciOiJ", _key_service(), MagicMock(), _LOCAL)
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_local_invalid_key_401():
    with pytest.raises(HTTPException) as ei:
        await get_management_principal("Bearer mlpal_sk_bad", _key_service(invalid=True),
                                       MagicMock(), _LOCAL)
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_managed_delegates_to_jwt_unchanged():
    managed = SimpleNamespace(auth_backend="managed")
    fake_user = AuthenticatedUser(id=7, email="u@x.com", cognito_sub="sub")
    with patch("mlpal_assistants_service.api.deps.get_current_user_from_jwt",
               AsyncMock(return_value=fake_user)) as m:
        p = await get_management_principal("Bearer jwt-token", MagicMock(), MagicMock(), managed)
    assert p.id == 7
    m.assert_awaited_once()  # managed path untouched
