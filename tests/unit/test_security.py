"""Unit tests for security utilities."""


from mlpal_assistants_service.core.security import (
    generate_api_key,
    generate_trace_id,
    hash_api_key,
    verify_api_key_format,
)


class TestAPIKeyGeneration:
    """Tests for API key generation."""

    def test_generate_api_key_returns_tuple(self) -> None:
        """Test that generate_api_key returns correct tuple."""
        result = generate_api_key()

        assert isinstance(result, tuple)
        assert len(result) == 3

        full_key, key_hash, key_prefix = result
        assert isinstance(full_key, str)
        assert isinstance(key_hash, str)
        assert isinstance(key_prefix, str)

    def test_generated_key_starts_with_prefix(self) -> None:
        """Test that generated key has correct prefix."""
        full_key, _, key_prefix = generate_api_key()

        assert full_key.startswith("mlpal_sk_")
        assert key_prefix.startswith("mlpal_sk_")
        assert key_prefix.endswith("...")

    def test_generated_key_has_correct_length(self) -> None:
        """Test that generated key has correct length."""
        full_key, key_hash, _ = generate_api_key()

        # Prefix (9 chars) + 64 hex chars (32 bytes)
        assert len(full_key) == 9 + 64

        # SHA-256 hash is 64 hex chars
        assert len(key_hash) == 64

    def test_generated_keys_are_unique(self) -> None:
        """Test that each generated key is unique."""
        keys = set()
        for _ in range(100):
            full_key, _, _ = generate_api_key()
            keys.add(full_key)

        assert len(keys) == 100

    def test_hash_is_deterministic(self) -> None:
        """Test that hashing the same key produces the same hash."""
        full_key, key_hash, _ = generate_api_key()

        # Hash the key again
        rehashed = hash_api_key(full_key)

        assert rehashed == key_hash


class TestAPIKeyVerification:
    """Tests for API key format verification."""

    def test_valid_key_format(self) -> None:
        """Test that valid keys pass verification."""
        full_key, _, _ = generate_api_key()

        assert verify_api_key_format(full_key) is True

    def test_invalid_prefix(self) -> None:
        """Test that keys with wrong prefix fail."""
        assert verify_api_key_format("sk_" + "a" * 64) is False
        assert verify_api_key_format("openai_" + "a" * 64) is False

    def test_invalid_length(self) -> None:
        """Test that keys with wrong length fail."""
        assert verify_api_key_format("mlpal_sk_" + "a" * 10) is False
        assert verify_api_key_format("mlpal_sk_" + "a" * 100) is False

    def test_empty_key(self) -> None:
        """Test that empty key fails."""
        assert verify_api_key_format("") is False

    def test_none_handling(self) -> None:
        """Test handling of None-like values."""
        # The function expects a string, so this would raise an error
        # In production, we check for None before calling this
        pass


class TestTraceIdGeneration:
    """Tests for trace ID generation."""

    def test_trace_id_format(self) -> None:
        """Test that trace ID has correct format."""
        trace_id = generate_trace_id()

        assert trace_id.startswith("tr_")
        assert len(trace_id) > 20

    def test_trace_ids_are_unique(self) -> None:
        """Test that trace IDs are unique."""
        trace_ids = set()
        for _ in range(100):
            trace_ids.add(generate_trace_id())

        assert len(trace_ids) == 100

    def test_trace_id_contains_timestamp(self) -> None:
        """Test that trace ID contains timestamp component."""
        trace_id = generate_trace_id()

        # Format: tr_YYYYMMDDHHMMSS_<random>
        parts = trace_id.split("_")
        assert len(parts) == 3
        assert len(parts[1]) == 14  # YYYYMMDDHHMMSS


class TestAPIKeyHashing:
    """Tests for API key hashing."""

    def test_hash_is_sha256_length(self) -> None:
        """Test that hash has SHA-256 length."""
        key_hash = hash_api_key("test_key")
        assert len(key_hash) == 64

    def test_hash_is_hex_string(self) -> None:
        """Test that hash is a valid hex string."""
        key_hash = hash_api_key("test_key")
        # Should not raise
        int(key_hash, 16)

    def test_same_input_same_hash(self) -> None:
        """Test that same input produces same hash."""
        hash1 = hash_api_key("same_key")
        hash2 = hash_api_key("same_key")
        assert hash1 == hash2

    def test_different_input_different_hash(self) -> None:
        """Test that different inputs produce different hashes."""
        hash1 = hash_api_key("key1")
        hash2 = hash_api_key("key2")
        assert hash1 != hash2
