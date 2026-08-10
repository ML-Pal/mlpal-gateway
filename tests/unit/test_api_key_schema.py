"""APIKeyResponse must tolerate the legacy dict permissions shape — one
dict-form bootstrap key must not 500 the whole key list (the 2026-08-06
OSS-console incident)."""

from __future__ import annotations

from datetime import UTC, datetime

from mlpal_assistants_service.schemas.api_key import APIKeyResponse

_BASE = {
    "id": 1,
    "name": "oss-admin",
    "key_prefix": "mlpal_sk_abc",
    "rate_limit_tier": "unlimited",
    "is_active": True,
    "created_at": datetime.now(UTC),
}


def test_dict_permissions_coerced_to_list():
    r = APIKeyResponse.model_validate({**_BASE, "permissions": {"admin": True, "*": True}})
    assert sorted(r.permissions) == ["*", "admin"]


def test_dict_permissions_drops_ungranted():
    r = APIKeyResponse.model_validate({**_BASE, "permissions": {"admin": True, "chat": False}})
    assert r.permissions == ["admin"]


def test_list_permissions_pass_through():
    r = APIKeyResponse.model_validate({**_BASE, "permissions": ["chat", "messages"]})
    assert r.permissions == ["chat", "messages"]
