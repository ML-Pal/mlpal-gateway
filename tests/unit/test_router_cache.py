"""Tests that the router caches session-independent copies, not live ORM rows.

Regression guard for the 2026-06-03 incident: the router cached live
ModelRegistry instances; once their session closed they were detached, and
reading an attribute that needed a refresh raised DetachedInstanceError, taking
down the OpenAI/meta-model chat paths. A transient copy (no session) can never
do that.
"""

from unittest.mock import MagicMock

from sqlalchemy import inspect

from mlpal_assistants_service.db.models import MetaModelRouting, ModelRegistry
from mlpal_assistants_service.services.router import ModelRouter


def _router() -> ModelRouter:
    return ModelRouter(MagicMock(), redis_client=None)


def test_detached_model_is_a_transient_copy():
    router = _router()
    source = ModelRegistry(
        id=1,
        model_tag="gpt-5.4",
        provider="openai",
        provider_model_id="gpt-5.4",
        display_name="GPT-5.4",
        capabilities=["chat"],
        pricing_tier="standard",
        priority=1,
        is_active=True,
        is_deprecated=False,
    )

    copy = router._detached_model(source)

    assert copy is not source
    # Transient instances have no session, so attribute reads never trigger a
    # refresh — this is precisely what avoids DetachedInstanceError.
    assert inspect(copy).transient is True
    # All fields the router/services read survive the copy.
    assert copy.model_tag == "gpt-5.4"
    assert copy.provider == "openai"
    assert copy.provider_model_id == "gpt-5.4"
    assert copy.is_active is True
    assert copy.is_deprecated is False


def test_detached_routing_is_a_transient_copy():
    router = _router()
    source = MetaModelRouting(
        id=7,
        meta_model_tag="mlpal",
        operation="chat",
        resolved_model_tag="gpt-5.4",
        priority=1,
        is_active=True,
        reason=None,
    )

    copy = router._detached_routing(source)

    assert copy is not source
    assert inspect(copy).transient is True
    assert copy.resolved_model_tag == "gpt-5.4"
    assert copy.meta_model_tag == "mlpal"
    assert copy.operation == "chat"
