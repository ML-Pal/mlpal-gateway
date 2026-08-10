"""Payload capture: config precedence, compression roundtrip, truncation, and
the off-by-default privacy posture. Pure logic — no DB/Redis."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

from mlpal_assistants_service.services.capture import (
    compress_body,
    decompress_body,
    resolve_config,
)


def _no_file(monkey_sections):
    return patch(
        "mlpal_assistants_service.services.capture.file_config_section",
        return_value=monkey_sections,
    )


# ── precedence: runtime > env > file > default(False) ────────────────────────


def test_default_is_off():
    with _no_file({}), patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MLPAL_CAPTURE_PAYLOADS", None)
        cfg = resolve_config(runtime_override=None)
    assert cfg.enabled is False
    assert cfg.source == "default"


def test_file_layer_applies():
    with _no_file({"enabled": True, "max_body_kb": 64, "retention_days": 3}):
        os.environ.pop("MLPAL_CAPTURE_PAYLOADS", None)
        cfg = resolve_config(runtime_override=None)
    assert cfg.enabled is True and cfg.source == "file"
    assert cfg.max_body_kb == 64 and cfg.retention_days == 3


def test_env_beats_file():
    with _no_file({"enabled": True}), patch.dict(os.environ, {"MLPAL_CAPTURE_PAYLOADS": "false"}):
        cfg = resolve_config(runtime_override=None)
    assert cfg.enabled is False and cfg.source == "env"


def test_runtime_beats_env():
    with _no_file({}), patch.dict(os.environ, {"MLPAL_CAPTURE_PAYLOADS": "false"}):
        cfg = resolve_config(runtime_override=True)
    assert cfg.enabled is True and cfg.source == "runtime"


# ── compression ──────────────────────────────────────────────────────────────


def test_compress_roundtrip_dict():
    body = {"model": "mlpal", "messages": [{"role": "user", "content": "héllo " * 100}]}
    blob, original, truncated = compress_body(body, max_body_kb=256)
    assert not truncated
    assert len(blob) < original  # text compresses
    assert json.loads(decompress_body(blob)) == body


def test_truncation_flags_and_marks():
    big = "x" * (300 * 1024)
    blob, original, truncated = compress_body(big, max_body_kb=1)
    assert truncated and original == 300 * 1024
    text = decompress_body(blob)
    assert text.endswith("... [truncated]")
    assert len(text) < 2 * 1024  # capped to ~1KB + marker


def test_truncation_preserves_valid_utf8():
    body = "é" * 2048  # 2-byte glyphs; a byte-cut would split one
    blob, _, truncated = compress_body(body, max_body_kb=1)
    assert truncated
    decompress_body(blob).encode("utf-8")  # must not raise
