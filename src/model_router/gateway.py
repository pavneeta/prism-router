from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from model_router.classifier import Classification, classify_messages
from model_router.config import (
    get_selection_policy,
    get_settings,
    load_benchmarks,
    load_models,
    load_policy,
)
from model_router.litellm_backend import (
    acompletion,
    apply_provider_cache_hints,
    completion_cost,
    extract_token_usage,
    provider_type,
)
from model_router.mirror import schedule_mirror_eval, should_mirror
from model_router.policy import RoutingDecision, estimate_input_tokens
from model_router.prompt_cache import get_prompt_cache
from model_router.rate_limit import get_rate_limiter
from model_router.safety import redact_secrets
from model_router.sessions import apply_session_classification, get_session_store
from model_router.telemetry import TelemetryEvent, TelemetryLogger, now_ts
from model_router.usage_metrics import get_usage_metrics

load_dotenv()

logger = logging.getLogger("model_router.gateway")


def _clear_self_referential_provider_bases() -> None:
    """Clients set OPENAI_API_BASE to this gateway; the gateway must hit real providers.

    If those env vars leak into the gateway process, LiteLLM posts back to itself and hangs.
    """
    import os

    markers = [
        "127.0.0.1:4000",
        "localhost:4000",
        "0.0.0.0:4000",
        "prism-router-production.up.railway.app",
    ]
    public = (os.environ.get("MODEL_ROUTER_PUBLIC_BASE") or "").strip().rstrip("/")
    if public:
        # Match host with or without scheme / trailing /v1
        markers.append(public.removeprefix("https://").removeprefix("http://").split("/")[0])
    for var in (
        "OPENAI_API_BASE",
        "OPENAI_BASE_URL",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_API_BASE",
        "FIREWORKS_API_BASE",
    ):
        val = os.environ.get(var, "")
        if any(m and m in val for m in markers):
            os.environ.pop(var, None)
            logger.info("cleared self-referential %s", var)


_clear_self_referential_provider_bases()

app = FastAPI(title="Prism Router", version="0.2.0")


def _openai_error(
    message: str,
    *,
    status_code: int,
    err_type: str = "invalid_request_error",
    code: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": redact_secrets(message) or message,
                "type": err_type,
                "param": None,
                "code": code,
            }
        },
    )


@app.exception_handler(HTTPException)
async def _http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if not isinstance(detail, str):
        detail = json.dumps(detail, default=str)
    err_type = "invalid_request_error" if exc.status_code < 500 else "server_error"
    if exc.status_code == 429:
        err_type = "rate_limit_error"
    elif exc.status_code == 502:
        err_type = "upstream_error"
    return _openai_error(detail, status_code=exc.status_code, err_type=err_type)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(_request: Request, _exc: Exception) -> JSONResponse:
    logger.exception("unhandled error")
    return _openai_error(
        "internal server error",
        status_code=500,
        err_type="server_error",
        code="internal_error",
    )


class _RateLimitMiddleware(BaseHTTPMiddleware):
    """In-process RPM limiter; skipped for health/ready probes."""

    _SKIP = {"/health", "/ready"}

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path in self._SKIP:
            return await call_next(request)
        settings = get_settings()
        limiter = get_rate_limiter()
        limiter.configure(settings.model_router_rate_limit_rpm)
        if settings.model_router_rate_limit_rpm <= 0:
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        if not limiter.allow(client):
            return _openai_error(
                f"Rate limit exceeded ({settings.model_router_rate_limit_rpm} rpm). "
                "Retry later or raise MODEL_ROUTER_RATE_LIMIT_RPM.",
                status_code=429,
                err_type="rate_limit_error",
                code="rate_limit_exceeded",
            )
        return await call_next(request)


def _configure_app_middleware() -> None:
    """Wire middleware without calling get_settings() (avoids caching Settings at import)."""
    import os

    raw = (os.environ.get("MODEL_ROUTER_CORS_ORIGINS") or "").strip()
    if raw:
        origins = ["*"] if raw == "*" else [o.strip() for o in raw.split(",") if o.strip()]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["x-request-id"],
        )
    app.add_middleware(_RateLimitMiddleware)


_configure_app_middleware()


class ChatMessage(BaseModel):
    role: str
    content: Any = ""


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any | None = None
    user: str | None = None


class ExplainRequest(BaseModel):
    messages: list[ChatMessage]
    tools: list[dict[str, Any]] | None = None
    model: str = "model-router/auto"
    session_id: str | None = None


def _telemetry() -> TelemetryLogger:
    settings = get_settings()
    return TelemetryLogger(path=Path(settings.model_router_telemetry_path))


def _prompt_text(messages: list[ChatMessage]) -> str:
    parts: list[str] = []
    for m in messages:
        if isinstance(m.content, str):
            parts.append(m.content)
        elif isinstance(m.content, list):
            for block in m.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
    return "\n".join(parts)


def _likely_prefix_reuse(messages: list[ChatMessage], tools: list[dict[str, Any]] | None) -> bool:
    if tools:
        return True
    if any(m.role == "system" for m in messages):
        return True
    # Multi-turn conversations usually share a growing prefix
    return len(messages) >= 3


def _deterministic_request(body: ChatCompletionRequest) -> bool:
    return body.temperature is None or body.temperature == 0


def _local_cache_key(body: ChatCompletionRequest) -> str:
    """Key by requested model so lookup can run before classify/route."""
    cache = get_prompt_cache()
    return cache.request_key(
        model=body.model,
        messages=[m.model_dump() for m in body.messages],
        tools=body.tools,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
    )


def _is_auto_model(requested_model: str, auto_ids: list[str] | None = None) -> bool:
    """True when the client asked Prism to select a model.

    Accepts configured ids plus any ``*/auto`` suffix (HolmesGPT LiteLLM often
    sends ``openai/auto``).
    """
    ids = auto_ids if auto_ids is not None else load_policy().auto_model_ids
    if requested_model in ids:
        return True
    return requested_model.endswith("/auto")


def _route(
    *,
    requested_model: str,
    messages: list[ChatMessage],
    tools: list[dict[str, Any]] | None,
    session_id: str | None = None,
) -> tuple[Classification, RoutingDecision | None, str]:
    """Returns classification, decision (if auto), and litellm model to call."""
    policy_cfg = load_policy()
    cache = get_prompt_cache()
    sessions = get_session_store()
    turn = classify_messages(
        [m.model_dump() for m in messages],
        tools=tools,
    )
    prior = sessions.get_task(session_id)
    classification = apply_session_classification(turn, prior=prior)
    sessions.set_task(session_id, classification)

    if _is_auto_model(requested_model, policy_cfg.auto_model_ids):
        affinity = cache.get_affinity(session_id) if policy_cfg.prompt_cache_enabled else None
        decision = get_selection_policy().select(
            task_type=classification.task_type,
            classification_confidence=classification.confidence,
            prompt_text=_prompt_text(messages),
            session_affinity=affinity,
            likely_prefix_reuse=_likely_prefix_reuse(messages, tools),
        )
        return classification, decision, decision.litellm_model
    # Passthrough: remap catalog ids (e.g. moonshot/kimi-k3) to provider litellm ids.
    deployment = get_selection_policy().enabled_deployment(requested_model)
    litellm_model = deployment.litellm_model if deployment is not None else requested_model
    return classification, None, litellm_model


def _decision_payload(decision: RoutingDecision) -> dict[str, Any]:
    return {
        "selected_model": decision.selected_model,
        "litellm_model": decision.litellm_model,
        "task_type": decision.task_type,
        "classification_confidence": decision.classification_confidence,
        "min_accuracy": decision.min_accuracy,
        "selected_accuracy": decision.selected_accuracy,
        "estimated_cost_usd": decision.estimated_cost_usd,
        "frontier_cost_usd": decision.frontier_cost_usd,
        "cost_delta_vs_frontier_usd": decision.cost_delta_vs_frontier_usd,
        "reason": decision.reason,
        "eligible_models": decision.eligible_models,
        "considered_models": decision.considered_models,
        "cache_layer": decision.cache_layer,
        "estimated_cached_tokens": decision.estimated_cached_tokens,
        "sticky_model": decision.sticky_model,
        "supports_prompt_caching": decision.supports_prompt_caching,
    }


def _classification_from_cached(payload: dict[str, Any]) -> Classification:
    mr = payload.get("model_router") or {}
    c = mr.get("classification") or {}
    return Classification(
        task_type=str(c.get("task_type", "general_chat")),
        confidence=float(c.get("confidence", 0.0)),
        signals=list(c.get("signals") or ["local_cache_hit"]),
    )


def _emit(
    *,
    request_id: str,
    session_id: str | None,
    body: ChatCompletionRequest,
    classification: Classification,
    decision: RoutingDecision | None,
    selected_model: str,
    litellm_model: str,
    route_mode: str,
    latency_ms: float,
    status: str,
    cache_hit: bool = False,
    cache_layer: str = "none",
    error: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cached_tokens: int | None = None,
    actual_cost_usd: float | None = None,
) -> None:
    est_cost = decision.estimated_cost_usd if decision else 0.0
    _telemetry().emit(
        TelemetryEvent(
            ts=now_ts(),
            request_id=request_id,
            session_id=session_id,
            route_mode=route_mode,
            requested_model=body.model,
            selected_model=selected_model,
            litellm_model=litellm_model,
            task_type=classification.task_type,
            classification_confidence=classification.confidence,
            classification_signals=classification.signals,
            policy_reason=decision.reason if decision else "passthrough",
            estimated_cost_usd=est_cost,
            frontier_cost_usd=decision.frontier_cost_usd if decision else 0.0,
            cost_delta_vs_frontier_usd=decision.cost_delta_vs_frontier_usd if decision else 0.0,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            actual_cost_usd=actual_cost_usd,
            latency_ms=latency_ms,
            status=status,
            error=error,
            cache_hit=cache_hit,
            cache_layer=cache_layer if cache_hit else (decision.cache_layer if decision else "none"),
            estimated_cached_tokens=decision.estimated_cached_tokens if decision else 0,
            sticky_model=decision.sticky_model if decision else None,
        )
    )
    get_session_store().record_event(
        session_id=session_id,
        task_type=classification.task_type,
        selected_model=selected_model,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=est_cost,
        actual_cost_usd=actual_cost_usd,
        frontier_cost_usd=decision.frontier_cost_usd if decision else 0.0,
        cost_delta_vs_frontier_usd=decision.cost_delta_vs_frontier_usd if decision else 0.0,
        cache_hit=cache_hit,
        estimated_cached_tokens=decision.estimated_cached_tokens if decision else 0,
    )
    get_usage_metrics().record(
        session_id=session_id,
        model=selected_model,
        provider=provider_type(litellm_model),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        est_cost_usd=est_cost,
        actual_cost_usd=actual_cost_usd,
    )


def _router_meta(
    classification: Classification,
    decision: RoutingDecision | None,
    *,
    cache_hit: bool,
    cache_layer: str,
) -> dict[str, Any]:
    return {
        "classification": {
            "task_type": classification.task_type,
            "confidence": classification.confidence,
            "signals": classification.signals,
        },
        "decision": _decision_payload(decision) if decision else None,
        "cache": {"hit": cache_hit, "layer": cache_layer},
    }


def _update_affinity(
    *,
    session_id: str | None,
    decision: RoutingDecision | None,
    prompt_tokens: int | None,
    messages: list[ChatMessage],
) -> None:
    policy_cfg = load_policy()
    if not (decision and session_id and policy_cfg.prompt_cache_enabled):
        return
    cache = get_prompt_cache()
    prefix_est = prompt_tokens or estimate_input_tokens(_prompt_text(messages))
    cache.set_affinity(
        session_id,
        model_id=decision.selected_model,
        litellm_model=decision.litellm_model,
        prefix_tokens_estimate=int(prefix_est),
    )


def _completion_kwargs(body: ChatCompletionRequest, litellm_model: str | None = None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if body.temperature is not None:
        kwargs["temperature"] = body.temperature
    if body.max_tokens is not None:
        kwargs["max_tokens"] = body.max_tokens
    if body.tool_choice is not None:
        kwargs["tool_choice"] = body.tool_choice
    # Newer OpenAI GPT-5.* chat models only accept default temperature.
    model = (litellm_model or body.model or "").lower()
    if "gpt-5" in model:
        kwargs.pop("temperature", None)
    return kwargs


@app.get("/health")
async def health() -> dict[str, Any]:
    """Liveness — process is up. Does not validate config or providers."""
    import os

    settings = get_settings()
    return {
        "status": "ok",
        "dry_run": settings.model_router_dry_run,
        "mirror_mode": settings.model_router_mirror_mode,
        "mirror_judge": settings.model_router_mirror_judge,
        "providers": {
            "openai": bool(os.getenv("OPENAI_API_KEY")),
            "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
            "fireworks": bool(os.getenv("FIREWORKS_API_KEY")),
        },
    }


@app.get("/ready")
async def ready() -> JSONResponse:
    """Readiness — config YAML loads. Does not validate provider key values."""
    try:
        policy = load_policy()
        benches = load_benchmarks()
        models = load_models()
        settings = get_settings()
        return JSONResponse(
            {
                "status": "ready",
                "config": {
                    "policy": True,
                    "benchmarks": len(benches.models),
                    "deployments": len(models.deployments),
                    "prompt_cache_enabled": policy.prompt_cache_enabled,
                },
                "dry_run": settings.model_router_dry_run,
                "mirror_mode": settings.model_router_mirror_mode,
                # In-memory cache/affinity — not shared across replicas
                "session_store": "in_memory",
                "note": (
                    "Session affinity and local prompt cache are in-memory per process. "
                    "With multiple replicas, sticky sessions are not guaranteed — "
                    "cache/affinity may miss across instances (routing still works)."
                ),
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _openai_error(
            f"config not ready: {exc}",
            status_code=503,
            err_type="server_error",
            code="not_ready",
        )


@app.get("/v1/router/sessions/{session_id}")
async def session_rollup(session_id: str) -> dict[str, Any]:
    """Per-session telemetry rollup (tokens, $, cache hits, task mix)."""
    rollup = get_session_store().get_rollup(session_id)
    task = get_session_store().get_task(session_id)
    if rollup is None and task is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "session_id": session_id,
        "task": (
            {
                "task_type": task.task_type,
                "confidence": task.confidence,
                "turns": task.turns,
            }
            if task
            else None
        ),
        "rollup": rollup.to_dict() if rollup else None,
    }


@app.get("/v1/router/metrics/usage")
async def usage_metrics(
    session_id: str | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """In-process token usage rollups by session, model, and provider.

    Unauthenticated like ``/ready`` and other ``/v1/router/*`` debug endpoints.
    Query filters: ``session_id``, ``model`` (catalog / selected id), ``provider``.
    """
    return get_usage_metrics().snapshot(
        session_id=session_id,
        model=model,
        provider=provider,
    )


class AnthropicMessageBlock(BaseModel):
    type: str = "text"
    text: str = ""


class AnthropicMessagesRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    max_tokens: int = 1024
    system: str | list[dict[str, Any]] | None = None
    temperature: float | None = None
    stream: bool = False
    tools: list[dict[str, Any]] | None = None


def _anthropic_to_chat_messages(body: AnthropicMessagesRequest) -> list[ChatMessage]:
    out: list[ChatMessage] = []
    if body.system:
        if isinstance(body.system, str):
            out.append(ChatMessage(role="system", content=body.system))
        elif isinstance(body.system, list):
            text = " ".join(
                str(b.get("text", "")) for b in body.system if isinstance(b, dict)
            )
            out.append(ChatMessage(role="system", content=text))
    for msg in body.messages:
        role = str(msg.get("role", "user"))
        content = msg.get("content", "")
        if isinstance(content, list):
            text = " ".join(
                str(b.get("text", "")) for b in content if isinstance(b, dict)
            )
            out.append(ChatMessage(role=role, content=text))
        else:
            out.append(ChatMessage(role=role, content=content))
    return out


@app.post("/v1/messages")
async def anthropic_messages(
    body: AnthropicMessagesRequest,
    request: Request,
    x_session_id: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> JSONResponse:
    """Anthropic Messages API compatibility (non-streaming MVP)."""
    _ = x_api_key  # accepted for client compatibility; gateway uses .env providers
    if body.stream:
        raise HTTPException(
            status_code=400,
            detail="streaming /v1/messages not implemented; use /v1/chat/completions?stream=true",
        )

    chat_messages = _anthropic_to_chat_messages(body)
    # Map Anthropic-style model aliases to router auto when requested
    requested = body.model
    policy_cfg = load_policy()
    if _is_auto_model(requested, policy_cfg.auto_model_ids):
        requested = "model-router/auto"

    chat_body = ChatCompletionRequest(
        model=requested,
        messages=chat_messages,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        stream=False,
        tools=body.tools,
    )
    # Reuse chat completions path logic via internal call
    response = await chat_completions(chat_body, request, x_session_id)
    # chat_completions returns JSONResponse — convert to Anthropic shape
    payload = json.loads(bytes(response.body).decode("utf-8"))
    if response.status_code >= 400:
        return response

    content_text = ""
    choices = payload.get("choices") or []
    if choices:
        content_text = str((choices[0].get("message") or {}).get("content") or "")
    usage = payload.get("usage") or {}
    anthropic_payload = {
        "id": payload.get("id") or f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": payload.get("model") or requested,
        "content": [{"type": "text", "text": content_text}],
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": usage.get("prompt_tokens") or 0,
            "output_tokens": usage.get("completion_tokens") or 0,
        },
        "model_router": payload.get("model_router"),
    }
    return JSONResponse(anthropic_payload)


@app.post("/v1/router/explain")
async def explain(
    body: ExplainRequest,
    x_session_id: str | None = Header(default=None),
) -> dict[str, Any]:
    session_id = body.session_id or x_session_id
    classification, decision, litellm_model = _route(
        requested_model=body.model,
        messages=body.messages,
        tools=body.tools,
        session_id=session_id,
    )
    return {
        "classification": {
            "task_type": classification.task_type,
            "confidence": classification.confidence,
            "signals": classification.signals,
        },
        "decision": _decision_payload(decision) if decision else None,
        "litellm_model": litellm_model,
        "session_id": session_id,
    }


async def _stream_completion(
    *,
    body: ChatCompletionRequest,
    request_id: str,
    session_id: str | None,
    classification: Classification,
    decision: RoutingDecision | None,
    selected_model: str,
    litellm_model: str,
    route_mode: str,
    started: float,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    kwargs: dict[str, Any],
) -> AsyncIterator[str]:
    status = "ok"
    error: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None
    try:
        call_kwargs = dict(kwargs)
        if tools is not None:
            call_kwargs["tools"] = tools
        # Ask OpenAI-family providers for a final usage chunk when streaming.
        if "stream_options" not in call_kwargs and provider_type(litellm_model) == "openai":
            call_kwargs["stream_options"] = {"include_usage": True}
        response = await acompletion(
            model=litellm_model,
            messages=messages,
            stream=True,
            **call_kwargs,
        )
        async for chunk in response:
            if hasattr(chunk, "model_dump"):
                data = chunk.model_dump()
            elif isinstance(chunk, dict):
                data = chunk
            else:
                data = dict(chunk)
            usage = data.get("usage") if isinstance(data, dict) else None
            if usage is None and hasattr(chunk, "usage"):
                usage = getattr(chunk, "usage", None)
            if usage is not None:
                p, c, cached = extract_token_usage(usage)
                if p is not None:
                    prompt_tokens = p
                if c is not None:
                    completion_tokens = c
                if cached is not None:
                    cached_tokens = cached
            yield f"data: {json.dumps(data, default=str)}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as exc:  # noqa: BLE001
        status = "error"
        error = redact_secrets(str(exc))
        err_payload = {
            "error": {
                "message": error or "stream error",
                "type": "upstream_error",
                "param": None,
                "code": "stream_error",
            },
        }
        yield f"data: {json.dumps(err_payload)}\n\n"
        yield "data: [DONE]\n\n"
    finally:
        latency_ms = (time.perf_counter() - started) * 1000
        try:
            _update_affinity(
                session_id=session_id,
                decision=decision,
                prompt_tokens=prompt_tokens,
                messages=body.messages,
            )
            _emit(
                request_id=request_id,
                session_id=session_id,
                body=body,
                classification=classification,
                decision=decision,
                selected_model=selected_model,
                litellm_model=litellm_model,
                route_mode=route_mode,
                latency_ms=latency_ms,
                status=status,
                error=error,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=cached_tokens,
                cache_layer=decision.cache_layer if decision else "none",
            )
        except Exception:  # noqa: BLE001 — best-effort post-stream bookkeeping
            pass


@app.post("/v1/chat/completions", response_model=None)
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    x_session_id: str | None = Header(default=None),
) -> JSONResponse | StreamingResponse:
    settings = get_settings()
    policy_cfg = load_policy()
    cache = get_prompt_cache()
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    started = time.perf_counter()

    # --- Local exact-match cache BEFORE classify/route (non-streaming only) ---
    cache_key: str | None = None
    if (
        not body.stream
        and policy_cfg.prompt_cache_enabled
        and _deterministic_request(body)
    ):
        cache_key = _local_cache_key(body)
        lookup = cache.get_local(cache_key)
        if lookup.hit and lookup.response is not None:
            latency_ms = (time.perf_counter() - started) * 1000
            payload = dict(lookup.response)
            mr = dict(payload.get("model_router") or {})
            mr["cache"] = {"hit": True, "layer": "local"}
            payload["model_router"] = mr
            classification = _classification_from_cached(payload)
            decision_meta = mr.get("decision") or {}
            selected_model = str(
                decision_meta.get("selected_model") or payload.get("model") or body.model
            )
            litellm_model = str(
                decision_meta.get("litellm_model") or payload.get("model") or body.model
            )
            cache_prompt, cache_completion, cache_cached = extract_token_usage(
                payload.get("usage")
            )
            _emit(
                request_id=request_id,
                session_id=x_session_id,
                body=body,
                classification=classification,
                decision=None,
                selected_model=selected_model,
                litellm_model=litellm_model,
                route_mode="auto" if _is_auto_model(body.model, policy_cfg.auto_model_ids) else "passthrough",
                latency_ms=latency_ms,
                status="ok",
                cache_hit=True,
                cache_layer="local",
                prompt_tokens=cache_prompt,
                completion_tokens=cache_completion,
                cached_tokens=cache_cached,
            )
            return JSONResponse(payload)

    classification, decision, litellm_model = _route(
        requested_model=body.model,
        messages=body.messages,
        tools=body.tools,
        session_id=x_session_id,
    )

    route_mode = "auto" if decision else "passthrough"
    selected_model = decision.selected_model if decision else body.model
    supports_caching = bool(decision.supports_prompt_caching) if decision else False
    if decision is None:
        # Passthrough: look up benchmark flag when available
        bench = get_selection_policy().benchmarks.models.get(body.model)
        supports_caching = bool(bench.supports_prompt_caching) if bench else False

    if settings.model_router_dry_run and not body.stream:
        latency_ms = (time.perf_counter() - started) * 1000
        _emit(
            request_id=request_id,
            session_id=x_session_id,
            body=body,
            classification=classification,
            decision=decision,
            selected_model=selected_model,
            litellm_model=litellm_model,
            route_mode=route_mode,
            latency_ms=latency_ms,
            status="dry_run",
            cache_layer=decision.cache_layer if decision else "none",
        )
        _update_affinity(
            session_id=x_session_id,
            decision=decision,
            prompt_tokens=None,
            messages=body.messages,
        )
        payload = {
            "id": f"chatcmpl-dryrun-{request_id}",
            "object": "chat.completion",
            "model": litellm_model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": (
                            f"[dry-run] would route to {litellm_model} "
                            f"for task={classification.task_type}"
                        ),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "model_router": _router_meta(
                classification,
                decision,
                cache_hit=False,
                cache_layer=decision.cache_layer if decision else "none",
            ),
        }
        if cache_key is not None:
            cache.put_local(cache_key, payload)
        return JSONResponse(payload)

    raw_messages = [m.model_dump() for m in body.messages]
    messages, tools, cache_extra = apply_provider_cache_hints(
        model=litellm_model,
        messages=raw_messages,
        tools=body.tools,
        supports_prompt_caching=supports_caching and policy_cfg.prompt_cache_enabled,
        session_id=x_session_id,
        fireworks_hide_thinking=policy_cfg.fireworks_hide_thinking,
    )
    kwargs = _completion_kwargs(body, litellm_model)
    kwargs.update(cache_extra)

    # --- Streaming path (skip local exact-cache) ---
    if body.stream:
        if settings.model_router_dry_run:
            # Synthetic SSE for dry-run so clients can exercise stream=true
            async def dry_stream() -> AsyncIterator[str]:
                chunk = {
                    "id": f"chatcmpl-dryrun-{request_id}",
                    "object": "chat.completion.chunk",
                    "model": litellm_model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": (
                                    f"[dry-run] would route to {litellm_model} "
                                    f"for task={classification.task_type}"
                                ),
                            },
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                done_chunk = {
                    "id": f"chatcmpl-dryrun-{request_id}",
                    "object": "chat.completion.chunk",
                    "model": litellm_model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(done_chunk)}\n\n"
                yield "data: [DONE]\n\n"
                latency_ms = (time.perf_counter() - started) * 1000
                _update_affinity(
                    session_id=x_session_id,
                    decision=decision,
                    prompt_tokens=None,
                    messages=body.messages,
                )
                _emit(
                    request_id=request_id,
                    session_id=x_session_id,
                    body=body,
                    classification=classification,
                    decision=decision,
                    selected_model=selected_model,
                    litellm_model=litellm_model,
                    route_mode=route_mode,
                    latency_ms=latency_ms,
                    status="dry_run",
                    cache_layer=decision.cache_layer if decision else "none",
                )

            return StreamingResponse(dry_stream(), media_type="text/event-stream")

        return StreamingResponse(
            _stream_completion(
                body=body,
                request_id=request_id,
                session_id=x_session_id,
                classification=classification,
                decision=decision,
                selected_model=selected_model,
                litellm_model=litellm_model,
                route_mode=route_mode,
                started=started,
                messages=messages,
                tools=tools,
                kwargs=kwargs,
            ),
            media_type="text/event-stream",
        )

    try:
        call_kwargs = dict(kwargs)
        if tools is not None:
            call_kwargs["tools"] = tools
        response = await acompletion(
            model=litellm_model,
            messages=messages,
            **call_kwargs,
        )
        status = "ok"
        error = None
    except Exception as exc:  # noqa: BLE001 — surface provider errors to client
        latency_ms = (time.perf_counter() - started) * 1000
        safe_err = redact_secrets(str(exc)) or "upstream error"
        _emit(
            request_id=request_id,
            session_id=x_session_id,
            body=body,
            classification=classification,
            decision=decision,
            selected_model=selected_model,
            litellm_model=litellm_model,
            route_mode=route_mode,
            latency_ms=latency_ms,
            status="error",
            error=safe_err,
        )
        raise HTTPException(status_code=502, detail=safe_err) from exc

    latency_ms = (time.perf_counter() - started) * 1000
    usage = getattr(response, "usage", None)
    prompt_tokens, completion_tokens, cached_tokens = extract_token_usage(usage)
    actual_cost = completion_cost(response)

    payload = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    payload["model_router"] = _router_meta(
        classification,
        decision,
        cache_hit=False,
        cache_layer=decision.cache_layer if decision else "none",
    )

    if should_mirror(
        settings,
        requested_model=body.model,
        route_mode=route_mode,
        stream=False,
    ):
        payload["model_router"]["mirror"] = {
            "enabled": True,
            "path": settings.model_router_mirror_path,
            "judge": settings.model_router_mirror_judge,
        }
        primary_content = None
        try:
            choices = payload.get("choices") or []
            if choices:
                primary_content = (choices[0].get("message") or {}).get("content")
        except Exception:  # noqa: BLE001
            primary_content = None
        primary_usage = None
        if usage is not None:
            primary_usage = (
                usage.model_dump()
                if hasattr(usage, "model_dump")
                else {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": getattr(usage, "total_tokens", None),
                }
            )
        # Base kwargs without primary-only cache extras for a clean shadow call.
        shadow_kwargs = _completion_kwargs(body, litellm_model)
        schedule_mirror_eval(
            settings=settings,
            request_id=request_id,
            session_id=x_session_id,
            requested_model=body.model,
            primary_litellm_model=litellm_model,
            primary_content=primary_content if isinstance(primary_content, str) else None,
            primary_usage=primary_usage,
            classification=classification,
            prompt_text=_prompt_text(body.messages),
            raw_messages=raw_messages,
            tools=body.tools,
            completion_kwargs=shadow_kwargs,
            likely_prefix_reuse=_likely_prefix_reuse(body.messages, body.tools),
            decision_payload_fn=_decision_payload,
        )

    if cache_key is not None:
        cache.put_local(cache_key, payload)

    _update_affinity(
        session_id=x_session_id,
        decision=decision,
        prompt_tokens=prompt_tokens,
        messages=body.messages,
    )

    _emit(
        request_id=request_id,
        session_id=x_session_id,
        body=body,
        classification=classification,
        decision=decision,
        selected_model=selected_model,
        litellm_model=litellm_model,
        route_mode=route_mode,
        latency_ms=latency_ms,
        status=status,
        error=error,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        actual_cost_usd=actual_cost,
        cache_layer=decision.cache_layer if decision else "none",
    )
    return JSONResponse(payload)


def main() -> None:
    import argparse
    import os

    ap = argparse.ArgumentParser(description="Prism Router — OpenAI-compatible gateway")
    ap.add_argument("--host", default=None, help="Bind host (default from settings)")
    ap.add_argument("--port", type=int, default=None, help="Bind port (default from settings)")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Route/classify only; do not call providers",
    )
    ap.add_argument(
        "--mirror-mode",
        action="store_true",
        help="Also run auto path for passthrough requests; log both outputs to JSONL",
    )
    ap.add_argument(
        "--mirror-path",
        default=None,
        help="Mirror JSONL path (default logs/mirror.jsonl)",
    )
    ap.add_argument(
        "--mirror-judge",
        action="store_true",
        help="After mirror completions, score primary vs auto with a small LLM judge",
    )
    ap.add_argument(
        "--mirror-judge-model",
        default=None,
        help="Judge model id (default openai/gpt-4o-mini)",
    )
    args = ap.parse_args()

    if args.dry_run:
        os.environ["MODEL_ROUTER_DRY_RUN"] = "true"
    if args.mirror_mode:
        os.environ["MODEL_ROUTER_MIRROR_MODE"] = "true"
    if args.mirror_path:
        os.environ["MODEL_ROUTER_MIRROR_PATH"] = args.mirror_path
    if args.mirror_judge:
        os.environ["MODEL_ROUTER_MIRROR_JUDGE"] = "true"
    if args.mirror_judge_model:
        os.environ["MODEL_ROUTER_MIRROR_JUDGE_MODEL"] = args.mirror_judge_model
    if args.host:
        os.environ["MODEL_ROUTER_HOST"] = args.host
    if args.port is not None:
        os.environ["MODEL_ROUTER_PORT"] = str(args.port)

    get_settings.cache_clear()
    _clear_self_referential_provider_bases()
    settings = get_settings()
    if settings.model_router_dry_run:
        logger.warning("MODEL_ROUTER_DRY_RUN=true — provider calls skipped")
    if settings.model_router_mirror_mode:
        logger.warning(
            "MODEL_ROUTER_MIRROR_MODE=true — shadow completions roughly double spend"
        )
    uvicorn.run(
        "model_router.gateway:app",
        host=settings.model_router_host,
        port=settings.model_router_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
