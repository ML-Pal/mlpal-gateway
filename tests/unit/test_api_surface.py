"""API surface contract.

Versioning policy (see api/mounting.py): the whole data plane is `/v1`; wires
are told apart by RESOURCE (messages = Anthropic, chat/completions = OpenAI),
not by version. `/v2` is reserved.

`/v1/messages` is the universal translating core in EVERY deployment. Two
transitional seams:

  * serve_legacy_v2_aliases (managed default True): the historical
    /v2/{messages,catalog,feedback} keep answering — same handlers — until
    yodex finishes moving to /v1 and alias traffic drains. OSS scrubs to False.
  * enable_bedrock_mantle_messages (default False): opt-in mounts the mantle
    passthrough at the scoped /mantle/v1/messages; it never owns /v1/messages.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI

import mlpal_assistants_service.main as m
from mlpal_assistants_service.api.mounting import mount_api
from mlpal_assistants_service.core.config import get_settings


def _paths(app: FastAPI) -> set[str]:
    return set(app.openapi().get("paths", {}).keys())


def _app(**overrides) -> FastAPI:
    settings = get_settings().model_copy(update=overrides)
    app = FastAPI()
    mount_api(app, settings)
    return app


def _oss_app() -> FastAPI:
    return _app(enable_bedrock_mantle_messages=False, serve_legacy_v2_aliases=False)


def _summary(app: FastAPI, path: str, method: str = "post") -> str:
    return app.openapi()["paths"][path][method].get("summary", "")


# ── canonical surface: identical in every deployment ─────────────────────────


def test_v1_messages_is_the_universal_core_everywhere():
    # The standardization invariant: clients need no per-deployment path logic.
    assert "Universal" in _summary(m.app, "/v1/messages")
    assert "Universal" in _summary(_oss_app(), "/v1/messages")


def test_default_surface():
    """The app's default surface: canonical /v1 always; /v2 aliases present
    exactly when this build's default says so (managed repo: True; the OSS
    build scrubs it to False)."""
    paths = _paths(m.app)
    assert {"/v1/messages", "/v1/messages/models", "/v1/catalog", "/v1/feedback"} <= paths
    assert {"/v1/chat/completions", "/v1/embeddings"} <= paths
    assert {"/admin/v1/keys", "/v1/keys"} <= paths
    assert "/mantle/v1/messages" not in paths  # mantle is opt-in only
    v2 = {"/v2/messages", "/v2/messages/models", "/v2/catalog", "/v2/feedback"}
    if get_settings().serve_legacy_v2_aliases:
        assert v2 <= paths
    else:
        assert not [p for p in paths if p.startswith("/v2")]


def test_v2_aliases_are_the_same_handlers():
    # Aliases must never fork behavior — same universal core on both paths.
    app = _app(serve_legacy_v2_aliases=True)
    assert "Universal" in _summary(app, "/v2/messages")


def test_v2_aliases_flip_off():
    paths = _paths(_app(serve_legacy_v2_aliases=False))
    assert "/v1/messages" in paths
    assert not [p for p in paths if p.startswith("/v2")]


def test_mantle_is_scoped_when_enabled():
    # The mantle module is excluded from the self-hosted distribution — there
    # the flag must produce a clear config error, not a mounted route.
    pytest.importorskip("mlpal_assistants_service.api.v1.messages")
    paths = _paths(_app(enable_bedrock_mantle_messages=True))
    assert "/mantle/v1/messages" in paths
    # even with mantle on, /v1/messages stays the universal core
    assert "Universal" in _summary(_app(enable_bedrock_mantle_messages=True), "/v1/messages")


def test_mantle_flag_without_module_is_a_clear_error():
    try:
        import mlpal_assistants_service.api.v1.messages  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="not part of this build"):
            _app(enable_bedrock_mantle_messages=True)


# ── self-hosted surface: clean /v1, no /v2 ───────────────────────────────────


def test_oss_surface_is_clean_v1_only():
    paths = _paths(_oss_app())
    assert {"/v1/messages", "/v1/messages/models", "/v1/catalog", "/v1/feedback"} <= paths
    assert {"/v1/chat/completions", "/v1/embeddings", "/admin/v1/keys"} <= paths
    # /v2 is reserved — nothing is mounted there in the OSS build.
    assert not [p for p in paths if p.startswith("/v2")]
