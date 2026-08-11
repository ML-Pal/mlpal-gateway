"""v2 universal core for /v2/messages.

Owns everything cross-cutting so every provider edge behaves identically:
model resolution (ModelRouter + allowlist), SSE transport + heartbeat, usage→CU,
wallet debit, and the Anthropic error envelope. Edges only produce Anthropic
wire bytes and report usage (see edges.py). v2-A wires the Anthropic edge.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from decimal import Decimal
from typing import Any

from fastapi.responses import Response, StreamingResponse

from mlpal_assistants_service.adapters.factory import get_adapter_factory
from mlpal_assistants_service.core.config import get_settings
from mlpal_assistants_service.core.exceptions import (
    BudgetExceededError,
    ModelAccessDeniedError,
    ModelNotAvailableError,
    ModelNotFoundError,
    RateLimitExceededError,
)
from mlpal_assistants_service.core.metrics import get_metrics
from mlpal_assistants_service.seams.billing import build_billing_gate, is_insufficient_wallet_error
from mlpal_assistants_service.services.messages_v2.anthropic_backend import get_anthropic_backend
from mlpal_assistants_service.services.messages_v2.anthropic_edge import AnthropicEdge
from mlpal_assistants_service.services.messages_v2.edges import ProviderEdge, RequestContext
from mlpal_assistants_service.services.messages_v2.errors import error_body
from mlpal_assistants_service.services.messages_v2.schemas import ValidatedRequest
from mlpal_assistants_service.services.messages_v2.translating_edge import TranslatingEdge

logger = logging.getLogger(__name__)

OPERATION = "chat"  # matches existing ModelPricing rows

# Providers that have a /v2/messages edge (anthropic native passthrough; openai
# and google via the translating edge). Bedrock has no edge yet.
SERVED_PROVIDERS = frozenset({"anthropic", "openai", "google"})

# Sentinel: an allowlist of ["*"] admits any served chat model (GA default),
# instead of an explicit per-tag pin list.
ALLOWLIST_WILDCARD = "*"

# Strong refs for fire-and-forget tasks (debit/capture) — the event loop keeps
# only weak references, so an unreferenced task can be GC'd mid-flight.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


def is_served_chat_model(model: Any) -> bool:
    """True if a resolved model can be served on /v2/messages under the wildcard
    policy: a chat-operation model on a provider that has an edge. Excludes
    image/embedding/tts/transcription models and unsupported providers (which
    would otherwise fail confusingly inside an adapter)."""
    if model.provider not in SERVED_PROVIDERS:
        return False
    caps = model.capabilities if isinstance(model.capabilities, dict) else {}
    return caps.get("operation", "chat") == "chat"


class ModelNotAllowed(Exception):
    """Model isn't on the v2 dev allowlist."""


class MessagesV2Core:
    def __init__(
        self,
        router: Any,
        usage_service: Any,
        pricing_service: Any,
        billing_gate: Any,
        *,
        rate_limiter: Any = None,
        policy: Any = None,
    ) -> None:
        self._router = router
        self._usage = usage_service
        self._pricing = pricing_service
        self._billing = billing_gate  # seams.billing.BillingGate (local or managed)
        self._rate_limiter = rate_limiter
        self._policy = policy
        self._settings = get_settings()

    # -- admission policy ---------------------------------------------------
    def _model_allowed(self, model: Any) -> bool:
        """Wildcard (["*"]) admits any served chat model; otherwise the model
        tag must be explicitly pinned in the allowlist."""
        allow = self._settings.messages_v2_allowlist
        if ALLOWLIST_WILDCARD in allow:
            return is_served_chat_model(model)
        return model.model_tag in allow

    # -- edge selection -----------------------------------------------------
    def _edge_for(self, provider: str) -> ProviderEdge:
        if provider == "anthropic":
            return AnthropicEdge(get_anthropic_backend(self._settings))
        if provider in ("openai", "google"):
            # Same translating edge for both: Anthropic surface ↔ OpenAI-common
            # ↔ provider adapter ↔ Anthropic wire (see translating_edge.py).
            return TranslatingEdge(get_adapter_factory().get(provider))
        raise ModelNotAllowed(f"provider '{provider}' not yet served by /v2/messages")

    # -- request handling ---------------------------------------------------
    async def handle(
        self,
        req: ValidatedRequest,
        api_key: Any,
        headers: Mapping[str, str],
        trace_id: str,
        *,
        surface: str = "v1_messages",
    ) -> Response:
        self._surface = surface
        try:
            # Resolve mlpal meta-models (mlpal / mlpal-turbo / mlpal-lite) to the
            # concrete chat model before admission + routing, exactly as /v1/chat
            # does — otherwise get_model(meta) 404s.
            resolved_tag, _routing = await self._router.resolve_meta_model(req.model, OPERATION)
            model = await self._router.get_model(resolved_tag)
        except ModelNotFoundError:
            return Response(error_body(404, f"model '{req.model}' not found"), 404, media_type="application/json")
        except ModelNotAvailableError as e:
            return Response(error_body(503, str(e)), 503, media_type="application/json")

        if not self._model_allowed(model):
            return Response(
                content=error_body(404, f"model '{req.model}' is not available on /v2/messages"),
                status_code=404,
                media_type="application/json",
            )

        # Admission — the SAME pipeline as /v1/chat (rate limit → billing gate →
        # per-key policy), mapped to the Anthropic error envelope. This surface
        # is the primary prod endpoint; a key blocked on /v1/chat must be
        # equally blocked here.
        try:
            if self._rate_limiter:
                await self._rate_limiter.check_request_limit(
                    str(api_key.user_id), getattr(api_key, "rate_limit_tier", None)
                )
            can_request, block_reason, _billing_existed = (
                await self._billing.can_make_request_cached(api_key.user_id)
            )
            if not can_request:
                return Response(
                    error_body(403, block_reason or "API access blocked"),
                    403,
                    media_type="application/json",
                )
            if self._policy is not None:
                self._policy.check_model_access(
                    getattr(api_key, "model_policy", None),
                    requested=req.model,
                    resolved=model.model_tag,
                )
                await self._policy.check_budgets(
                    api_key.id, getattr(api_key, "budgets", None)
                )
        except RateLimitExceededError as e:
            return Response(error_body(429, str(e)), 429, media_type="application/json")
        except (ModelAccessDeniedError, BudgetExceededError) as e:
            return Response(error_body(403, str(e)), 403, media_type="application/json")

        cc_metadata = _cc_metadata(headers, req.metadata)
        if model.model_tag != req.model:  # served via a meta-model alias
            cc_metadata["requested_model"] = req.model
        ctx = RequestContext(
            # Resolved concrete tag drives pricing, usage_logs, and the response
            # `model` field (what actually served the request).
            model_tag=model.model_tag,
            provider=model.provider,
            provider_model_id=model.provider_model_id,
            backend=self._settings.anthropic_messages_backend,
            trace_id=trace_id,
            api_key=api_key,
            headers=headers,
            cc_metadata=cc_metadata,
        )
        try:
            edge = self._edge_for(model.provider)
        except ModelNotAllowed as e:
            return Response(error_body(400, str(e)), 400, media_type="application/json")

        t0 = time.perf_counter()
        if req.stream:
            return StreamingResponse(
                self._stream_with_heartbeat(edge, req, ctx, t0),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        result = await edge.invoke(req, ctx)
        compute_units = await self._meter(ctx, int((time.perf_counter() - t0) * 1000))
        # Opt-in payload capture — a task spawn only; enabled-check + zlib all
        # happen inside the task (see services/capture.py).
        _spawn(
            _capture_v2(ctx.trace_id, req.body, result.body, getattr(self._usage, "redis", None))
        )
        # Surface CU on the Anthropic-wire response via headers (the body stays a
        # faithful Anthropic Messages object). Streaming can't do this — headers
        # are sent before the CU is known — so streamed requests are billing-only.
        return Response(
            content=result.body,
            status_code=result.status_code,
            media_type=result.media_type,
            headers=_cu_headers(compute_units),
        )

    # -- streaming transport (heartbeat) ------------------------------------
    async def _stream_with_heartbeat(
        self, edge: ProviderEdge, req: ValidatedRequest, ctx: RequestContext, t0: float
    ) -> AsyncIterator[bytes]:
        """Pipe the edge's raw Anthropic-SSE bytes through, emitting `: ping`
        keepalives during silence so long reasoning/tool phases can't trip the
        client/ALB idle timeouts. Producer/queue decouples the heartbeat from
        the edge generator (same pattern as /v1/chat); meter after completion."""
        interval = self._settings.messages_v2_heartbeat_interval
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        # Accumulate the provider's SSE bytes for opt-in payload capture (the
        # non-streaming path captures result.body; without this, streaming
        # clients — yodex streams everything — never produce payloads). Hard
        # cap bounds memory; capture_payload truncates to max_body_kb anyway.
        capture_buf = bytearray()
        capture_cap = 1024 * 1024

        async def _produce() -> None:
            try:
                async for chunk in edge.stream(req, ctx):
                    await queue.put(("chunk", chunk))
            except Exception as e:  # noqa: BLE001
                await queue.put(("error", e))
            finally:
                await queue.put(("end", None))

        producer = asyncio.create_task(_produce())
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=interval)
                except TimeoutError:
                    yield b": ping\n\n"
                    continue
                if kind == "chunk":
                    if len(capture_buf) < capture_cap:
                        capture_buf += payload[: capture_cap - len(capture_buf)]
                    yield payload
                elif kind == "error":
                    logger.error(f"[v2.messages] stream error trace={ctx.trace_id}: {payload}")
                    # Mid-stream provider failure: emit an Anthropic error event.
                    yield b"event: error\ndata: " + error_body(502, "upstream stream error") + b"\n\n"
                    break
                else:  # end
                    break
        finally:
            producer.cancel()
            try:
                await producer
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            await self._meter(ctx, int((time.perf_counter() - t0) * 1000))
            _spawn(
                _capture_v2(
                    ctx.trace_id, req.body, bytes(capture_buf),
                    getattr(self._usage, "redis", None),
                )
            )

    # -- telemetry + billing (never raises) ---------------------------------
    async def _meter(self, ctx: RequestContext, latency_ms: int) -> Decimal:
        is_success = ctx.status_code == 200 and ctx.usage is not None
        input_tokens = ctx.usage.input if is_success else 0
        output_tokens = ctx.usage.output if is_success else 0
        # Billed CU = the model's pass-through cost, no markup (locked pricing:
        # flat tier fee is the revenue; tokens at cost). Stored rates carry the
        # legacy markup column, so divide it back out.
        compute_units = Decimal("0")
        if is_success:
            rates = await self._resolve_cu_rates(ctx.model_tag)
            if rates is None:
                logger.warning(f"[v2.messages] no pricing for {ctx.model_tag}; CU=0 trace={ctx.trace_id}")
            else:
                compute_units = ctx.usage.compute_units(*rates)

        logger.info(
            f"[v2.messages] trace={ctx.trace_id} model={ctx.model_tag} provider={ctx.provider} "
            f"backend={ctx.backend} status={ctx.status_code} latency_ms={latency_ms} "
            f"usage={json.dumps(ctx.usage.raw) if ctx.usage else None} cu={compute_units}"
        )
        # Reasoning-budget empty completion: the turn "succeeded" (200) but the
        # model produced no visible output because reasoning consumed max_tokens.
        # We surface stop_reason=max_tokens faithfully; here we make it observable
        # (distinct log + metric + a usage_log flag) so the reliability property is
        # monitorable, not just anecdotal. The client sees a clear signal to retry
        # with a larger budget — we never silently inflate it (that would surprise
        # and over-bill the caller).
        if is_success and ctx.empty_completion:
            logger.warning(
                f"[v2.messages] empty_completion (reasoning budget exhausted) "
                f"trace={ctx.trace_id} model={ctx.model_tag} provider={ctx.provider} "
                f"output_tokens={output_tokens}"
            )
            get_metrics().put_metric_sync(
                "EmptyCompletion", 1, dimensions={"provider": ctx.provider, "model": ctx.model_tag}
            )
        try:
            await self._usage.record_usage(
                user_id=str(ctx.api_key.user_id),
                api_key_id=str(ctx.api_key.id),
                trace_id=ctx.trace_id,
                model_tag=ctx.model_tag,
                provider=ctx.provider,
                operation=OPERATION,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                compute_units=compute_units,
                latency_ms=latency_ms,
                status="success" if is_success else "error",
                error_code=None if is_success else f"http_{ctx.status_code}",
                # "pending" until _post_billing resolves it (debited / failed_* /
                # not_applicable) — same lifecycle as /v1/chat, so DebitRetryWorker
                # and reconciliation see this surface identically.
                wallet_debit_status=(
                    "pending" if (is_success and compute_units > 0) else "not_applicable"
                ),
                # `api` tags which mount served the call (v1_messages vs the
                # deprecated v2_messages alias) — drives the alias-drain query.
                cc_metadata={
                    **ctx.cc_metadata,
                    "api": getattr(self, "_surface", "v1_messages"),
                    "provider_message_id": ctx.provider_message_id,
                    # Cache observability: input_tokens above CONTAINS the cached
                    # portion; these make prompt-cache effectiveness queryable
                    # (cc_metadata->>'cache_read_input_tokens') per trace.
                    **(
                        {
                            "cache_read_input_tokens": ctx.usage.cache_read,
                            "cache_creation_input_tokens": ctx.usage.cache_write,
                        }
                        if is_success and ctx.usage is not None
                        else {}
                    ),
                    **({"empty_completion": True} if ctx.empty_completion else {}),
                },
            )
        except Exception:  # pragma: no cover - telemetry must never 500 the request
            logger.exception(f"[v2.messages] record_usage failed trace={ctx.trace_id}")

        if is_success and compute_units > 0:
            _spawn(self._post_billing(ctx, compute_units, input_tokens + output_tokens))

        return compute_units

    async def _resolve_cu_rates(self, model_tag: str) -> tuple[Decimal, Decimal] | None:
        """Per-token CU rates at PASS-THROUGH: the stored cu_rates include the
        row's legacy markup_multiplier (generated columns), so divide the row's
        own markup back out — the same source of truth the v1 chat path uses
        (ModelPricing.calculate_provider_cost). Never a config knob: a setting
        that must mirror per-row DB state is a correctness trap (caught live:
        OSS rows carry markup 1.0 while the old setting said 3.0 → 3× under-
        billing on /v1/messages vs /v1/chat for identical usage)."""
        pricing = await self._pricing.get_pricing(model_tag, OPERATION)
        if pricing is None:
            return None
        divisor = Decimal("1000") if pricing.rate_unit == "per_1k_tokens" else Decimal("1000000")
        markup = pricing.markup_multiplier or Decimal("1")
        return (
            pricing.input_cu_rate / divisor / markup,
            pricing.output_cu_rate / divisor / markup,
        )

    async def _post_billing(self, ctx: RequestContext, compute_units: Decimal, total_tokens: int) -> None:
        """Post-response billing, mirroring /v1/chat's background flow: gated
        wallet debit with an honest wallet_debit_status lifecycle (pending →
        debited / failed_retryable / failed_permanent / not_applicable), token
        rate-limit accrual, and per-key budget accrual. Runs on a fresh session —
        the request session is closed by the time this task executes."""
        from mlpal_assistants_service.db.session import async_session_factory
        from mlpal_assistants_service.services.usage import UsageService

        redis = getattr(self._usage, "redis", None)
        try:
            async with async_session_factory() as bg_session:
                gate = build_billing_gate(bg_session, redis)
                bg_usage = UsageService(bg_session, redis)
                if not await gate.is_wallet_debit_active():
                    # Gating off (or local billing): the ledger derives spend from
                    # usage rows; debiting the wallet too would double-count.
                    await bg_usage.mark_wallet_debit_status(ctx.trace_id, "not_applicable")
                else:
                    try:
                        await gate.debit_wallet_usage(
                            user_id=ctx.api_key.user_id,
                            compute_units=compute_units,
                            usage_ref=ctx.trace_id,
                        )
                    except Exception as debit_error:  # noqa: BLE001 — classified below
                        await bg_usage.mark_wallet_debit_status(
                            ctx.trace_id,
                            (
                                "failed_permanent"
                                if is_insufficient_wallet_error(debit_error)
                                else "failed_retryable"
                            ),
                            error=str(debit_error),
                        )
                    else:
                        await bg_usage.mark_wallet_debit_status(ctx.trace_id, "debited")
                await bg_session.commit()

            if self._rate_limiter:
                await self._rate_limiter.record_tokens(str(ctx.api_key.user_id), total_tokens)
            if self._policy is not None:
                await self._policy.record_key_usage(
                    ctx.api_key.id, getattr(ctx.api_key, "budgets", None), compute_units
                )
        except Exception:  # pragma: no cover — billing telemetry must never crash the loop
            logger.exception(
                f"[v2.messages] post-billing failed user={ctx.api_key.user_id} trace={ctx.trace_id}"
            )


async def _capture_v2(
    trace_id: str, request_body: Any, response_body: bytes | str, redis: Any
) -> None:
    """Background capture for the universal messages core (non-streaming)."""
    try:
        from mlpal_assistants_service.services.capture import capture_payload, capture_state

        cfg = await capture_state.config(redis)
        if not cfg.enabled:
            return
        body = (
            response_body.decode("utf-8", "replace")
            if isinstance(response_body, bytes)
            else response_body
        )
        await capture_payload(trace_id, request_body, body, cfg.max_body_kb)
    except Exception:  # noqa: BLE001 — debug data must never raise
        logger.exception(f"[v2.messages] capture failed trace={trace_id}")


def _cu_headers(compute_units: Decimal) -> dict[str, str]:
    """CU envelope for the Anthropic-wire response (body stays untouched)."""
    return {"X-MLPal-Compute-Units": str(compute_units)}


def _cc_metadata(headers: Mapping[str, str], metadata: dict[str, Any]) -> dict[str, Any]:
    """Claude-Code / Anthropic attribution signals for usage logs."""
    return {
        "cc_session_id": headers.get("x-claude-code-session-id"),
        "cc_agent_id": headers.get("x-claude-code-agent-id"),
        "cc_parent_agent_id": headers.get("x-claude-code-parent-agent-id"),
        "anthropic_user_id": metadata.get("user_id") if isinstance(metadata, dict) else None,
        "anthropic_version_header": headers.get("anthropic-version"),
        "anthropic_beta_header": headers.get("anthropic-beta"),
    }
