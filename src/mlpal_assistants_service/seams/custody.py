"""Custody seam for tenant secrets (BYOK provider keys, BYOM endpoint keys).

The gateway never persists raw provider keys — it stores an opaque
`secret_ref` and resolves the plaintext through one of two drivers, chosen by
`MLPAL_CUSTODY_DRIVER`:

* ``secrets_service`` (managed): mlpal-secrets-service internal API with an
  ``mlpal_svc_*`` identity and ``X-Mlpal-Act-As-User-Id`` — KMS envelope
  encryption, per-access audit, dual (service+user) attribution.
* ``local`` (dev / self-hosted): AES-GCM with a key from
  ``MLPAL_CUSTODY_LOCAL_KEY``; ciphertext lives in the connection row itself
  (secret_ref carries it). Dev-grade by design — documented as such.

Both drivers expose store/reveal/delete keyed by (user_id, name).
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any, Protocol

import httpx

from mlpal_assistants_service.core.config import get_settings

logger = logging.getLogger(__name__)

PURPOSE = "tenant_connection_key"


class CustodyDriver(Protocol):
    async def store(self, user_id: int, name: str, value: str) -> str:
        """Persist the secret; return an opaque secret_ref."""
        ...

    async def reveal(self, user_id: int, secret_ref: str) -> str:
        """Return the plaintext for a ref. Do not log the result."""
        ...

    async def delete(self, user_id: int, secret_ref: str) -> None: ...


class SecretsServiceDriver:
    """Managed custody via mlpal-secrets-service internal routes."""

    def __init__(self, base_url: str, svc_token: str) -> None:
        self._base = base_url.rstrip("/")
        self._token = svc_token

    def _headers(self, user_id: int) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "X-Mlpal-Act-As-User-Id": str(user_id),
        }

    async def store(self, user_id: int, name: str, value: str) -> str:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self._base}/api/v1/internal/secrets",
                headers=self._headers(user_id),
                json={
                    "name": name,
                    "value": value,
                    "purpose": PURPOSE,
                    "tags": {"source": "gateway-connections"},
                },
            )
            if resp.status_code == 409:
                # Name exists for this user — replace: find, delete, recreate.
                existing = await client.get(
                    f"{self._base}/api/v1/internal/secrets",
                    headers=self._headers(user_id),
                    params={"name": name},
                )
                existing.raise_for_status()
                for row in existing.json().get("items", []):
                    if row.get("name") == name:
                        await client.delete(
                            f"{self._base}/api/v1/internal/secrets/{row['id']}",
                            headers=self._headers(user_id),
                        )
                resp = await client.post(
                    f"{self._base}/api/v1/internal/secrets",
                    headers=self._headers(user_id),
                    json={
                        "name": name,
                        "value": value,
                        "purpose": PURPOSE,
                        "tags": {"source": "gateway-connections"},
                    },
                )
            resp.raise_for_status()
            return str(resp.json()["id"])

    async def reveal(self, user_id: int, secret_ref: str) -> str:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self._base}/api/v1/internal/secrets/{secret_ref}/reveal",
                headers=self._headers(user_id),
            )
            resp.raise_for_status()
            return resp.json()["value"]

    async def delete(self, user_id: int, secret_ref: str) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(
                f"{self._base}/api/v1/internal/secrets/{secret_ref}",
                headers=self._headers(user_id),
            )
            if resp.status_code not in (204, 404):
                resp.raise_for_status()


class LocalDriver:
    """Dev/self-host custody: AES-GCM, key from env, ciphertext in the ref.

    secret_ref format: ``local:v1:<b64(nonce)>:<b64(ciphertext)>``. The AAD
    binds user_id so a ref can't be replayed across tenants.
    """

    def __init__(self, key_b64: str) -> None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        raw = base64.urlsafe_b64decode(key_b64 + "=" * (-len(key_b64) % 4))
        if len(raw) not in (16, 24, 32):
            raise ValueError("MLPAL_CUSTODY_LOCAL_KEY must be 16/24/32 bytes (base64url)")
        self._aead = AESGCM(raw)

    async def store(self, user_id: int, name: str, value: str) -> str:
        nonce = os.urandom(12)
        ct = self._aead.encrypt(nonce, value.encode(), str(user_id).encode())
        return f"local:v1:{base64.urlsafe_b64encode(nonce).decode()}:{base64.urlsafe_b64encode(ct).decode()}"

    async def reveal(self, user_id: int, secret_ref: str) -> str:
        _, _, nonce_b64, ct_b64 = secret_ref.split(":", 3)
        nonce = base64.urlsafe_b64decode(nonce_b64)
        ct = base64.urlsafe_b64decode(ct_b64)
        return self._aead.decrypt(nonce, ct, str(user_id).encode()).decode()

    async def delete(self, user_id: int, secret_ref: str) -> None:
        return None  # ciphertext lives in the row; deleting the row is enough


def build_custody(settings: Any = None) -> CustodyDriver:
    settings = settings or get_settings()
    driver = getattr(settings, "custody_driver", "local")
    if driver == "secrets_service":
        if not (settings.custody_secrets_service_url and settings.custody_secrets_service_token):
            raise RuntimeError(
                "MLPAL_CUSTODY_DRIVER=secrets_service requires "
                "MLPAL_SECRETS_SERVICE_URL and MLPAL_SECRETS_SERVICE_TOKEN"
            )
        return SecretsServiceDriver(
            settings.custody_secrets_service_url, settings.custody_secrets_service_token
        )
    if not settings.custody_local_key:
        raise RuntimeError("local custody requires MLPAL_CUSTODY_LOCAL_KEY")
    return LocalDriver(settings.custody_local_key)
