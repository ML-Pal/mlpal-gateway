"""Chat service - main orchestrator for chat completions.

The ChatService coordinates all components to handle chat requests:
- ModelRouter: Route to appropriate provider adapter
- PricingService: Calculate compute units
- BillingRepository: Check if user can make requests
- UsageService: Track and record usage
- RateLimiter: Enforce rate limits
- CircuitBreaker: Handle provider failures

Gateway design: all capabilities (tools, structured output, MCP) are passed
through to the provider. No server-side agentic loops.

Billing Flow (pay-as-you-go):
1. Check billing status (active/suspended/blocked) — cached in Redis
2. Check spending limit if set
3. Execute request
4. Fire-and-forget: billing increment, usage record, token recording
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from mlpal_assistants_service.adapters import (
    CircuitBreakerOpen,
)
from mlpal_assistants_service.core.exceptions import (
    ModelNotFoundError,
    ProviderError,
    QuotaExceededError,
    UnsupportedCapabilityError,
    WalletEmptyError,
)
from mlpal_assistants_service.repositories.usage_repository import UsageRepository
from mlpal_assistants_service.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    CostInfo,
    FunctionCallSchema,
    StreamChunk,
    TokenUsage,
    ToolCallSchema,
)
from mlpal_assistants_service.seams.billing import build_billing_gate, is_insufficient_wallet_error
from mlpal_assistants_service.services.capture import capture_payload, capture_state
from mlpal_assistants_service.services.policy import PolicyService
from mlpal_assistants_service.services.pricing import PricingService
from mlpal_assistants_service.services.rate_limiter import RateLimiter

if TYPE_CHECKING:
    from mlpal_assistants_service.adapters.base import ToolDefinition
    from mlpal_assistants_service.schemas.chat import ToolDefinitionSchema
from mlpal_assistants_service.services.router import ModelRouter
from mlpal_assistants_service.services.usage import UsageService

logger = logging.getLogger(__name__)


class ChatService:
    """
    Main orchestration service for chat completions.

    Handles the full request lifecycle:
    1. Rate limiting check (pipelined Redis)
    2. Billing status check (Redis-cached)
    3. Capability validation
    4. Model routing and adapter selection
    5. Request execution with circuit breaker (pass-through)
    6. Cost calculation
    7. Fire-and-forget: billing increment, usage recording, token recording

    Usage:
        service = ChatService(session, redis_client)
        response = await service.chat(
            user_id=123,
            api_key_id=456,
            request=ChatCompletionRequest(
                model="gpt-5.2",
                messages=[{"role": "user", "content": "Hello!"}],
            ),
        )
    """

    def __init__(
        self,
        session: AsyncSession,
        redis_client: redis.Redis | None = None,
        sqs_client: Any | None = None,
        shared_caches: dict | None = None,
    ) -> None:
        self.session = session
        self.redis = redis_client
        self._sqs_client = sqs_client

        # Initialize component services
        self._router = ModelRouter(session, redis_client)
        self._pricing = PricingService(session, redis_client)
        self._billing = build_billing_gate(session, redis_client)
        self._usage = UsageService(session, redis_client, sqs_client)
        self._rate_limiter = RateLimiter(redis_client) if redis_client else None
        # Per-key policy engine. Pre-check reconciles budget spend from the
        # request session's usage repo; accrual (post-request) is Redis-only.
        self._policy = PolicyService(redis_client, UsageRepository(session))

        # Inject shared caches for hot-path optimization (avoids per-request DB hits)
        if shared_caches:
            if shared_caches.get("model_cache"):
                self._router._local_cache = shared_caches["model_cache"]
            if shared_caches.get("routing_cache"):
                self._router._routing_cache = shared_caches["routing_cache"]
            if shared_caches.get("pricing_cache"):
                self._pricing._local_cache = shared_caches["pricing_cache"]

        # Track background tasks to prevent GC
        self._background_tasks: set[asyncio.Task] = set()

    def _fire_and_forget(self, coro: Any) -> None:
        """Schedule a coroutine as a fire-and-forget background task."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _post_request_background(
        self,
        user_id: int,
        api_key_id: int,
        trace_id: str,
        resolved_model_tag: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        compute_units: Decimal,
        latency_ms: int,
        billing_needs_ensure: bool,
        sqs_client: Any | None = None,
        budgets: list | None = None,
    ) -> None:
        """Background task for post-provider steps.

        Uses its own DB session since the request session is already closed.
        """
        from mlpal_assistants_service.db.session import async_session_factory

        try:
            async with async_session_factory() as bg_session:
                bg_billing = build_billing_gate(bg_session, self.redis)
                bg_usage = UsageService(bg_session, self.redis, sqs_client)

                # Ensure billing status if needed (new user)
                if billing_needs_ensure:
                    await bg_billing.ensure_billing_status(user_id)

                # Record usage (SQS or DB)
                await bg_usage.record_usage(
                    user_id=str(user_id),
                    api_key_id=str(api_key_id),
                    trace_id=trace_id,
                    model_tag=resolved_model_tag,
                    provider=provider,
                    operation="chat",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    compute_units=compute_units,
                    latency_ms=latency_ms,
                    status="success",
                    wallet_debit_status="pending",
                )

                # CU v3: skip wallet debit when gating is off. The frontend
                # computes effective balance as wallet - sum(cu_aggregates);
                # debiting the wallet too would double-count.
                if not await bg_billing.is_wallet_debit_active():
                    await bg_usage.mark_wallet_debit_status(
                        trace_id, "not_applicable"
                    )
                else:
                    try:
                        await bg_billing.debit_wallet_usage(
                            user_id=user_id,
                            compute_units=compute_units,
                            usage_ref=trace_id,
                        )
                    except Exception as debit_error:
                        await bg_usage.mark_wallet_debit_status(
                            trace_id,
                            (
                                "failed_permanent"
                                if is_insufficient_wallet_error(debit_error)
                                else "failed_retryable"
                            ),
                            error=str(debit_error),
                        )
                    else:
                        await bg_usage.mark_wallet_debit_status(trace_id, "debited")

                await bg_session.commit()

            # Record tokens for rate limiting (Redis only, no DB session needed)
            if self._rate_limiter:
                total_tokens = input_tokens + output_tokens
                await self._rate_limiter.record_tokens(str(user_id), total_tokens)

            # Accrue this call's CU onto the key's spend budgets (Redis only).
            await self._policy.record_key_usage(api_key_id, budgets, compute_units)

        except Exception as e:
            logger.error("Background post-request failed", exc_info=e)

    async def chat(
        self,
        user_id: int,
        api_key_id: int,
        request: ChatCompletionRequest,
        tier: str = "standard",
        model_policy: dict | None = None,
        budgets: list | None = None,
    ) -> ChatCompletionResponse:
        """
        Execute a chat completion request.

        All capabilities (tools, structured output, MCP) are passed through
        to the provider in a single adapter.chat() call.

        Args:
            user_id: User ID (integer)
            api_key_id: API key ID (integer)
            request: Chat completion request
            tier: Rate limit tier

        Returns:
            ChatCompletionResponse

        Raises:
            ModelNotFoundError: If model doesn't exist
            QuotaExceededError: If user is over quota
            RateLimitExceededError: If rate limited
            UnsupportedCapabilityError: If model doesn't support requested features
            ProviderError: If provider API fails
            CircuitBreakerOpen: If circuit is open (provider unavailable)
        """
        trace_id = str(uuid.uuid4())
        start_time = time.perf_counter()

        try:
            # 1. Check rate limits (pipelined — single Redis round-trip)
            if self._rate_limiter:
                await self._rate_limiter.check_request_limit(str(user_id), tier)

            # 2. Check billing status (Redis-cached — single Redis GET)
            (
                can_request,
                block_reason,
                billing_existed,
            ) = await self._billing.can_make_request_cached(user_id)
            if not can_request:
                from mlpal_assistants_service.repositories.billing_repository import (
                    WALLET_EMPTY_MESSAGE,
                )

                if block_reason == WALLET_EMPTY_MESSAGE:
                    raise WalletEmptyError(block_reason)
                raise QuotaExceededError(
                    message=block_reason or "API access blocked",
                    limit=0.0,
                    current_usage=0.0,
                )

            # 3. Get adapter with circuit breaker, resolving meta-models
            (
                adapter,
                provider_model_id,
                breaker,
                model_info,
                routing_metadata,
            ) = await self._router.get_adapter_with_breaker_for_operation(
                request.model,
                operation="chat",
            )

            # For pricing/usage, use the resolved model if this was a meta-model
            resolved_model_tag = (
                routing_metadata.resolved_model if routing_metadata else request.model
            )

            # 3b. Per-key policy gate (no-op when the key has no policy). Model
            # access is checked against the requested tag AND the resolved model
            # so an alias can't reach a denied model; budgets deny (402) once any
            # window is exhausted. Both run before the paid provider call.
            self._policy.check_model_access(
                model_policy, requested=request.model, resolved=resolved_model_tag
            )
            await self._policy.check_budgets(api_key_id, budgets)

            # 4. Capability validation
            capabilities = adapter.get_model_capabilities(provider_model_id)

            if request.tools and not capabilities.supports_tools:
                raise UnsupportedCapabilityError(
                    capability="tools",
                    model=request.model,
                    suggestions=["gpt-5.2", "claude-opus-4.5", "gemini-3-pro"],
                )

            if (
                request.response_format
                and request.response_format.type != "text"
                and not capabilities.supports_structured_output
            ):
                raise UnsupportedCapabilityError(
                    capability="structured_output",
                    model=request.model,
                    suggestions=["gpt-5.2", "claude-opus-4.5", "gemini-3-pro"],
                )

            if request.mcp_servers and not capabilities.supports_mcp:
                raise UnsupportedCapabilityError(
                    capability="mcp",
                    model=request.model,
                    suggestions=["gpt-5.2", "claude-opus-4.5"],
                )

            # 5. Convert messages and tools
            messages = self._convert_messages(request.messages)
            adapter_tools = self._convert_tool_schemas(request.tools) if request.tools else None
            response_format = self._convert_response_format(request.response_format)
            mcp_servers = self._convert_mcp_servers(request.mcp_servers)

            # 6. Single pass-through call to adapter
            async with breaker:
                response = await adapter.chat(
                    model=provider_model_id,
                    messages=messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    top_p=request.top_p,
                    stop=request.stop,
                    tools=adapter_tools,
                    tool_choice=request.tool_choice,
                    response_format=response_format,
                    mcp_servers=mcp_servers,
                )

            # 7. Calculate latency and compute units
            latency_ms = int((time.perf_counter() - start_time) * 1000)

            cu = await self._pricing.calculate_compute_units(
                model_tag=resolved_model_tag,
                input_units=response.usage.input_tokens,
                output_units=response.usage.output_tokens,
            )
            compute_units = cu

            # 8. Fire-and-forget: billing increment, usage record, token recording
            self._fire_and_forget(
                self._post_request_background(
                    user_id=user_id,
                    api_key_id=api_key_id,
                    trace_id=trace_id,
                    resolved_model_tag=resolved_model_tag,
                    provider=model_info.provider,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    compute_units=compute_units,
                    latency_ms=latency_ms,
                    billing_needs_ensure=not billing_existed,
                    sqs_client=self._sqs_client,
                    budgets=budgets,
                )
            )

            # 9. Build response
            tool_calls = self._convert_adapter_tool_calls(response.tool_calls)

            # Parse structured data if response_format was used
            data = None
            if (
                request.response_format
                and request.response_format.type != "text"
                and response.content
            ):
                try:
                    data = json.loads(response.content)
                except json.JSONDecodeError:
                    data = None

            chat_response = ChatCompletionResponse(
                content=response.content if response.content else None,
                role="assistant",
                finish_reason=response.finish_reason or "stop",
                tool_calls=tool_calls,
                data=data,
                cost=CostInfo(
                    model_name=resolved_model_tag,
                    provider=model_info.provider,
                    tokens=TokenUsage(
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                        total_tokens=response.usage.total_tokens,
                    ),
                    latency_ms=latency_ms,
                    compute_units=float(compute_units),
                ),
                metadata={
                    "trace_id": trace_id,
                    "provider_model": provider_model_id,
                },
                routing=routing_metadata,
            )
            # Opt-in payload capture — a task spawn; the enabled check and all
            # serialization happen inside the background task.
            self._maybe_capture(trace_id, request, chat_response)
            return chat_response

        except CircuitBreakerOpen as e:
            # Record failed request
            await self._record_failure(
                user_id=user_id,
                api_key_id=api_key_id,
                trace_id=trace_id,
                model_tag=request.model,
                error_code="circuit_open",
                start_time=start_time,
            )
            raise ProviderError(
                message=f"Provider temporarily unavailable: {e}",
                provider=request.model.split("-")[0] if "-" in request.model else "unknown",
                status_code=503,
            )

        except Exception as e:
            # Record failed request
            error_code = type(e).__name__
            await self._record_failure(
                user_id=user_id,
                api_key_id=api_key_id,
                trace_id=trace_id,
                model_tag=request.model,
                error_code=error_code,
                start_time=start_time,
                error_detail=str(e),
            )
            raise

    async def chat_stream(
        self,
        user_id: int,
        api_key_id: int,
        request: ChatCompletionRequest,
        tier: str = "standard",
        model_policy: dict | None = None,
        budgets: list | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """
        Execute a streaming chat completion request.

        Yields StreamChunk objects as content is generated.
        The final chunk includes cost information.

        Args:
            user_id: User ID (integer)
            api_key_id: API key ID (integer)
            request: Chat completion request (stream=True)
            tier: Rate limit tier

        Yields:
            StreamChunk objects
        """
        trace_id = str(uuid.uuid4())
        start_time = time.perf_counter()

        try:
            # 1. Check rate limits
            if self._rate_limiter:
                await self._rate_limiter.check_request_limit(str(user_id), tier)

            # 2. Check billing status (cached)
            (
                can_request,
                block_reason,
                billing_existed,
            ) = await self._billing.can_make_request_cached(user_id)
            if not can_request:
                from mlpal_assistants_service.repositories.billing_repository import (
                    WALLET_EMPTY_MESSAGE,
                )

                if block_reason == WALLET_EMPTY_MESSAGE:
                    raise WalletEmptyError(block_reason)
                raise QuotaExceededError(
                    message=block_reason or "API access blocked",
                    limit=0.0,
                    current_usage=0.0,
                )

            # 3. Get adapter with circuit breaker, resolving meta-models
            (
                adapter,
                provider_model_id,
                breaker,
                model_info,
                routing_metadata,
            ) = await self._router.get_adapter_with_breaker_for_operation(
                request.model,
                operation="chat",
            )

            # For pricing/usage, use the resolved model if this was a meta-model
            resolved_model_tag = (
                routing_metadata.resolved_model if routing_metadata else request.model
            )

            # 3b. Per-key policy gate (no-op when the key has no policy). Model
            # access is checked against the requested tag AND the resolved model
            # so an alias can't reach a denied model; budgets deny (402) once any
            # window is exhausted. Both run before the paid provider call.
            self._policy.check_model_access(
                model_policy, requested=request.model, resolved=resolved_model_tag
            )
            await self._policy.check_budgets(api_key_id, budgets)

            # 4. Capability validation
            capabilities = adapter.get_model_capabilities(provider_model_id)

            if request.tools and not capabilities.supports_tools:
                raise UnsupportedCapabilityError(
                    capability="tools",
                    model=request.model,
                    suggestions=["gpt-5.2", "claude-opus-4.5", "gemini-3-pro"],
                )
            if (
                request.response_format
                and request.response_format.type != "text"
                and not capabilities.supports_structured_output
            ):
                raise UnsupportedCapabilityError(
                    capability="structured_output",
                    model=request.model,
                    suggestions=["gpt-5.2", "claude-opus-4.5", "gemini-3-pro"],
                )
            if request.mcp_servers and not capabilities.supports_mcp:
                raise UnsupportedCapabilityError(
                    capability="mcp",
                    model=request.model,
                    suggestions=["gpt-5.2", "claude-opus-4.5"],
                )

            # 5. Convert messages and tools
            messages = self._convert_messages(request.messages)
            adapter_tools = self._convert_tool_schemas(request.tools) if request.tools else None
            response_format = self._convert_response_format(request.response_format)
            mcp_servers = self._convert_mcp_servers(request.mcp_servers)

            # Accumulated for opt-in payload capture (cheap string appends).
            streamed_parts: list[str] = []

            # 6. Execute streaming request with circuit breaker
            async with breaker:
                async for chunk in adapter.chat_stream(
                    model=provider_model_id,
                    messages=messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    top_p=request.top_p,
                    stop=request.stop,
                    tools=adapter_tools,
                    tool_choice=request.tool_choice,
                    response_format=response_format,
                    mcp_servers=mcp_servers,
                ):
                    if chunk.done:
                        if chunk.content:
                            streamed_parts.append(chunk.content)
                        final_usage = chunk.usage
                        latency_ms = int((time.perf_counter() - start_time) * 1000)

                        # Calculate compute units
                        if final_usage:
                            cu = await self._pricing.calculate_compute_units(
                                model_tag=resolved_model_tag,
                                input_units=final_usage.input_tokens,
                                output_units=final_usage.output_tokens,
                            )
                            compute_units = cu

                            # Fire-and-forget post-request steps
                            self._fire_and_forget(
                                self._post_request_background(
                                    user_id=user_id,
                                    api_key_id=api_key_id,
                                    trace_id=trace_id,
                                    resolved_model_tag=resolved_model_tag,
                                    provider=model_info.provider,
                                    input_tokens=final_usage.input_tokens,
                                    output_tokens=final_usage.output_tokens,
                                    compute_units=compute_units,
                                    latency_ms=latency_ms,
                                    billing_needs_ensure=not billing_existed,
                                    budgets=budgets,
                                )
                            )

                            # Yield final chunk with cost and routing
                            yield StreamChunk(
                                content=chunk.content,
                                done=True,
                                tool_calls=self._convert_adapter_tool_calls(chunk.tool_calls),
                                finish_reason=chunk.finish_reason,
                                cost=CostInfo(
                                    model_name=resolved_model_tag,
                                    provider=model_info.provider,
                                    tokens=TokenUsage(
                                        input_tokens=final_usage.input_tokens,
                                        output_tokens=final_usage.output_tokens,
                                        total_tokens=final_usage.total_tokens,
                                    ),
                                    latency_ms=latency_ms,
                                    compute_units=float(compute_units),
                                ),
                                routing=routing_metadata,
                            )
                            self._maybe_capture(
                                trace_id,
                                request,
                                {
                                    "role": "assistant",
                                    "content": "".join(streamed_parts),
                                    "finish_reason": chunk.finish_reason,
                                    "streamed": True,
                                },
                            )
                        else:
                            yield StreamChunk(
                                content=chunk.content,
                                done=True,
                                tool_calls=self._convert_adapter_tool_calls(chunk.tool_calls),
                                finish_reason=chunk.finish_reason,
                                routing=routing_metadata,
                            )
                    else:
                        # Mid-stream chunk: text delta and/or a completed tool call.
                        if chunk.content:
                            streamed_parts.append(chunk.content)
                        yield StreamChunk(
                            content=chunk.content,
                            done=False,
                            tool_calls=self._convert_adapter_tool_calls(chunk.tool_calls),
                        )

        except CircuitBreakerOpen as e:
            await self._record_failure(
                user_id=user_id,
                api_key_id=api_key_id,
                trace_id=trace_id,
                model_tag=request.model,
                error_code="circuit_open",
                start_time=start_time,
            )
            raise ProviderError(
                message=f"Provider temporarily unavailable: {e}",
                provider=request.model.split("-")[0] if "-" in request.model else "unknown",
                status_code=503,
            )

        except Exception as e:
            error_code = type(e).__name__
            await self._record_failure(
                user_id=user_id,
                api_key_id=api_key_id,
                trace_id=trace_id,
                model_tag=request.model,
                error_code=error_code,
                start_time=start_time,
                error_detail=str(e),
            )
            raise

    async def get_cost_estimate(
        self,
        model_tag: str,
        input_tokens: int,
        output_tokens: int = 0,
    ) -> dict[str, Any]:
        """
        Get a cost estimate for a request.

        Args:
            model_tag: Model identifier
            input_tokens: Estimated input tokens
            output_tokens: Estimated output tokens

        Returns:
            Cost breakdown dictionary
        """
        return await self._pricing.get_cost_breakdown(
            model_tag=model_tag,
            input_units=input_tokens,
            output_units=output_tokens,
        )

    # =========================================================================
    # Conversion Helpers
    # =========================================================================

    def _convert_tool_schemas(
        self,
        tools: list["ToolDefinitionSchema"],
    ) -> list["ToolDefinition"]:
        """Convert API tool schemas to adapter ToolDefinition objects."""
        from mlpal_assistants_service.adapters.base import ToolDefinition

        return [
            ToolDefinition(
                name=t.function.name,
                description=t.function.description,
                parameters=t.function.parameters,
                strict=t.function.strict,
            )
            for t in tools
        ]

    def _convert_adapter_tool_calls(
        self,
        raw_tool_calls: list[dict[str, Any]] | None,
    ) -> list[ToolCallSchema] | None:
        """Convert adapter raw tool_calls dicts to ToolCallSchema objects."""
        if not raw_tool_calls:
            return None

        return [
            ToolCallSchema(
                id=tc["id"],
                type="function",
                function=FunctionCallSchema(
                    name=tc["function"]["name"],
                    arguments=(
                        tc["function"]["arguments"]
                        if isinstance(tc["function"]["arguments"], str)
                        else json.dumps(tc["function"]["arguments"])
                    ),
                ),
                thought_signature=tc.get("thought_signature"),
            )
            for tc in raw_tool_calls
        ]

    def _convert_response_format(
        self,
        response_format: Any | None,
    ) -> dict[str, Any] | None:
        """Convert ResponseFormat schema to dict for adapter."""
        if response_format is None:
            return None
        result: dict[str, Any] = {"type": response_format.type}
        if response_format.json_schema:
            result["json_schema"] = {
                "name": response_format.json_schema.name,
                "schema": response_format.json_schema.schema_,
                "strict": response_format.json_schema.strict,
            }
            if response_format.json_schema.description:
                result["json_schema"]["description"] = response_format.json_schema.description
        return result

    def _convert_mcp_servers(
        self,
        mcp_servers: list[Any] | None,
    ) -> list[dict[str, Any]] | None:
        """Convert MCPServerConfig schemas to dicts for adapter."""
        if not mcp_servers:
            return None
        return [
            {
                "url": s.url,
                "name": s.name,
                "auth_token": s.auth_token,
                "allowed_tools": s.allowed_tools,
                "require_approval": s.require_approval,
            }
            for s in mcp_servers
        ]

    def _convert_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        """Convert schema messages to adapter format."""
        result = []
        for msg in messages:
            converted: dict[str, Any] = {
                "role": msg.role,
                "content": msg.content,
            }
            if msg.files:
                converted["files"] = [
                    {
                        "type": f.type,
                        "source": "url" if f.url else "base64",
                        "data": f.url or f.base64,
                        "mime_type": f.mime_type,
                    }
                    for f in msg.files
                ]
            if msg.tool_calls:
                converted["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                        **(
                            {"thought_signature": tc.thought_signature}
                            if tc.thought_signature
                            else {}
                        ),
                    }
                    for tc in msg.tool_calls
                ]
            if msg.tool_call_id:
                converted["tool_call_id"] = msg.tool_call_id
            if msg.name:
                converted["name"] = msg.name
            result.append(converted)
        return result

    async def _record_failure(
        self,
        user_id: int,
        api_key_id: int,
        trace_id: str,
        model_tag: str,
        error_code: str,
        start_time: float,
        error_detail: str | None = None,
    ) -> None:
        """Record a failed request for tracking."""
        try:
            latency_ms = int((time.perf_counter() - start_time) * 1000)

            # Try to get model info for provider
            try:
                model_info = await self._router.get_model(model_tag)
                provider = model_info.provider
            except ModelNotFoundError:
                provider = "unknown"

            await self._usage.record_usage(
                user_id=str(user_id),
                api_key_id=str(api_key_id),
                trace_id=trace_id,
                model_tag=model_tag,
                provider=provider,
                operation="chat",
                input_tokens=0,
                output_tokens=0,
                compute_units=Decimal("0"),
                latency_ms=latency_ms,
                status="error",
                error_code=error_code,
                # The actual provider/exception text — without this a failed
                # trace shows only the exception class name, and the operator
                # has to grep container logs to learn what went wrong.
                cc_metadata={"error_detail": error_detail[:500]} if error_detail else None,
            )
        except Exception as e:
            logger.warning(f"Failed to record error usage: {e}")

    def _maybe_capture(self, trace_id: str, request_body: Any, response_body: Any) -> None:
        """Schedule opt-in payload capture — entirely off the request path.

        The enabled check itself happens inside the task (10s-cached), so a
        disabled capture costs one task spawn and nothing else."""

        async def _run() -> None:
            try:
                cfg = await capture_state.config(self.redis)
                if not cfg.enabled:
                    return
                body = (
                    request_body.model_dump(exclude_none=True)
                    if hasattr(request_body, "model_dump")
                    else request_body
                )
                resp = (
                    response_body.model_dump(exclude_none=True)
                    if hasattr(response_body, "model_dump")
                    else response_body
                )
                await capture_payload(trace_id, body, resp, cfg.max_body_kb)
            except Exception:  # noqa: BLE001 — debug data must never raise
                logger.exception(f"capture task failed trace={trace_id}")

        self._fire_and_forget(_run())
