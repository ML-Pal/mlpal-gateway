"""POST /v2/messages — universal Anthropic-Messages endpoint (v2-A: Anthropic).

Thin API layer: auth + scope, light request validation, then hand to
MessagesV2Core (which owns routing, the provider edge, SSE transport/heartbeat,
telemetry, and the Anthropic error envelope). v1 paths are untouched.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from mlpal_assistants_service.api.deps import (
    CurrentAPIKey,
    ModelRouterDep,
    PricingServiceDep,
    UsageServiceDep,
)
from mlpal_assistants_service.core.config import get_settings
from mlpal_assistants_service.core.security import generate_trace_id
from mlpal_assistants_service.repositories import UsageRepository
from mlpal_assistants_service.seams.billing import build_billing_gate
from mlpal_assistants_service.services.policy import PolicyService
from mlpal_assistants_service.services.rate_limiter import RateLimiter
from mlpal_assistants_service.services.messages_v2.core import (
    ALLOWLIST_WILDCARD,
    SERVED_PROVIDERS,
    MessagesV2Core,
    is_served_chat_model,
)
from mlpal_assistants_service.services.messages_v2.errors import error_body
from mlpal_assistants_service.services.messages_v2.schemas import (
    InvalidMessagesRequest,
    validate,
)

router = APIRouter()


def _require_messages_scope(api_key) -> None:
    # Same scopes as /v1/messages: route-specific "messages" or grandfathered "chat".
    if not (api_key.has_permission("messages") or api_key.has_permission("chat")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key does not have permission for messages",
        )


@router.post(
    "",
    summary="Universal Anthropic Messages API",
    description=(
        "Anthropic-Messages wire-faithful endpoint with real provider "
        "translation. v2-A serves Anthropic models via the shared core."
    ),
)
async def create_messages_v2(
    request: Request,
    api_key: CurrentAPIKey,
    model_router: ModelRouterDep,
    usage_service: UsageServiceDep,
    pricing_service: PricingServiceDep,
) -> Response:
    _require_messages_scope(api_key)

    raw = await request.body()
    try:
        req = validate(raw)
    except InvalidMessagesRequest as e:
        return Response(error_body(400, str(e)), status_code=400, media_type="application/json")

    # Same admission stack as /v1/chat: billing seam (local = allow-all, no
    # callouts), Redis rate limiter, and the per-key policy engine.
    redis = getattr(usage_service, "redis", None)
    session = model_router.session
    core = MessagesV2Core(
        model_router,
        usage_service,
        pricing_service,
        build_billing_gate(session, redis),
        rate_limiter=RateLimiter(redis) if redis else None,
        policy=PolicyService(redis, UsageRepository(session)),
    )
    # Tag which mount served this call: canonical /v1/messages vs the
    # deprecated /v2 alias. "v2_messages" matches historical rows, so the
    # alias-drain query (migration Phase 3) is one WHERE clause.
    surface = "v2_messages" if request.url.path.startswith("/v2") else "v1_messages"
    return await core.handle(req, api_key, request.headers, generate_trace_id(), surface=surface)


@router.get(
    "/models",
    summary="List models available on /v2/messages with capabilities",
)
async def list_v2_models(api_key: CurrentAPIKey, model_router: ModelRouterDep) -> JSONResponse:
    """Capability advertisement for the models /v2/messages serves: capabilities
    read from the registry, plus reasoning/caching derived per provider. All
    served providers reason (Anthropic extended thinking, OpenAI gpt-5.x,
    Gemini 3 thinking) and surface cache reads in usage, so both are advertised
    for every served provider. Under the wildcard allowlist this lists every
    served chat model; with an explicit allowlist it lists those pinned tags."""
    _require_messages_scope(api_key)
    settings = get_settings()

    if ALLOWLIST_WILDCARD in settings.messages_v2_allowlist:
        candidates = [
            m for m in await model_router.list_models() if is_served_chat_model(m)
        ]
    else:
        candidates = []
        for tag in settings.messages_v2_allowlist:
            try:
                candidates.append(await model_router.get_model(tag))
            except Exception:  # noqa: BLE001 — skip unresolvable tags in the listing
                continue

    out = []
    for m in candidates:
        caps = m.capabilities if isinstance(m.capabilities, dict) else {}
        out.append({
            "id": m.model_tag,
            "display_name": m.display_name,
            "provider": m.provider,
            "max_output_tokens": m.max_output_tokens,
            "capabilities": {
                "tools": bool(caps.get("tools", True)),
                "vision": bool(caps.get("vision", True)),
                "reasoning": m.provider in SERVED_PROVIDERS,
                "caching": m.provider in SERVED_PROVIDERS,
            },
        })
    return JSONResponse({"data": out})
