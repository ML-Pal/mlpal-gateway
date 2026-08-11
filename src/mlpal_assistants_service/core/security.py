"""Security utilities for API key generation and validation."""

import hashlib
import secrets
from datetime import datetime

from mlpal_assistants_service.core.config import get_settings

CDE_API_KEY_PREFIX = "cde_sk_"


def generate_api_key(prefix: str | None = None) -> tuple[str, str, str]:
    """
    Generate a new API key.

    Args:
        prefix: Optional key prefix. Defaults to settings.api_key_prefix
            (`mlpal_sk_`). Pass `CDE_API_KEY_PREFIX` for CDE-pod-scoped
            keys — same threat model (bearer token), different lifetime
            and permission scope so a separate prefix gives ops clarity
            in logs and lets us revoke en-masse without touching user
            keys.

    Returns:
        Tuple of (full_key, key_hash, key_prefix)
        - full_key: The complete key to show to user once
        - key_hash: SHA-256 hash for storage
        - key_prefix: First 12 chars for identification (e.g., "mlpal_sk_abc...")
    """
    settings = get_settings()
    effective_prefix = prefix if prefix is not None else settings.api_key_prefix

    # Generate random bytes and encode as hex
    random_bytes = secrets.token_bytes(settings.api_key_bytes)
    random_part = random_bytes.hex()

    # Full key with prefix
    full_key = f"{effective_prefix}{random_part}"

    # Hash for storage (never store plaintext)
    key_hash = hash_api_key(full_key)

    # Prefix for display (shows prefix + first 8 chars of random part)
    key_prefix = f"{effective_prefix}{random_part[:8]}..."

    return full_key, key_hash, key_prefix


def is_known_api_key_prefix(token: str) -> bool:
    """True if `token` starts with any prefix we issue (mlpal_sk_ or
    cde_sk_). Used by the auth dependency to route between API-key
    validation and JWT validation."""
    settings = get_settings()
    return token.startswith(settings.api_key_prefix) or token.startswith(CDE_API_KEY_PREFIX)


def hash_api_key(api_key: str) -> str:
    """
    Hash an API key using SHA-256.

    Args:
        api_key: The plaintext API key

    Returns:
        Hex-encoded SHA-256 hash
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def verify_api_key_format(api_key: str) -> bool:
    """
    Verify that an API key has the correct format. Accepts any prefix
    we issue (user keys: mlpal_sk_; CDE-pod-scoped keys: cde_sk_).

    Args:
        api_key: The API key to verify

    Returns:
        True if format is valid
    """
    settings = get_settings()

    for prefix in (settings.api_key_prefix, CDE_API_KEY_PREFIX):
        if api_key.startswith(prefix):
            expected_length = len(prefix) + (settings.api_key_bytes * 2)
            return len(api_key) == expected_length
    return False


def generate_trace_id() -> str:
    """Generate a unique trace ID for request tracking."""
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    random_part = secrets.token_hex(8)
    return f"tr_{timestamp}_{random_part}"
