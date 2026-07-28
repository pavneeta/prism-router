from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from model_router.classifier import Classification, classify_messages
from model_router.config import get_selection_policy, get_settings, load_policy
from model_router.litellm_backend import acompletion, apply_provider_cache_hints, completion_cost
from model_router.policy import RoutingDecision, estimate_input_tokens
from model_router.prompt_cache import get_prompt_cache
from model_router.telemetry import TelemetryEvent, TelemetryLogger, now_ts

load_dotenv()

app = FastAPI(title="Model-Router", version="0.1.0")


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
    classification = classify_messages(
        [m.model_dump() for m in messages],
        tools=tools,
    )
    if requested_model in policy_cfg.auto_model_ids:
        affinity = cache.get_affinity(session_id) if policy_cfg.prompt_cache_enabled else None
        decision = get_selection_policy().select(
            task_type=classification.task_type,
            classification_confidence=classification.confidence,
            prompt_text=_prompt_text(messages),
            session_affinity=affinity,
            likely_prefix_reuse=_likely_prefix_reuse(messages, tools),
        )
        return classification, decision, decision.litellm_model
    return classification, None, requested_model


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
    actual_cost_usd: float | None = None,
) -> None:
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
            estimated_cost_usd=decision.estimated_cost_usd if decision else 0.0,
            frontier_cost_usd=decision.frontier_cost_usd if decision else 0.0,
            cost_delta_vs_frontier_usd=decision.cost_delta_vs_frontier_usd if decision else 0.0,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
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


def _completion_kwargs(body: ChatCompletionRequest) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if body.temperature is not None:
        kwargs["temperature"] = body.temperature
    if body.max_tokens is not None:
        kwargs["max_tokens"] = body.max_tokens
    if body.tool_choice is not None:
        kwargs["tool_choice"] = body.tool_choice
    return kwargs


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
    try:
        call_kwargs = dict(kwargs)
        if tools is not None:
            call_kwargs["tools"] = tools
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
            yield f"data: {json.dumps(data, default=str)}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as exc:  # noqa: BLE001
        status = "error"
        error = str(exc)
        err_payload = {
            "error": {"message": str(exc), "type": "model_router_stream_error"},
        }
        yield f"data: {json.dumps(err_payload)}\n\n"
        yield "data: [DONE]\n\n"
    finally:
        latency_ms = (time.perf_counter() - started) * 1000
        try:
            _update_affinity(
                session_id=session_id,
                decision=decision,
                prompt_tokens=None,
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
            _emit(
                request_id=request_id,
                session_id=x_session_id,
                body=body,
                classification=classification,
                decision=None,
                selected_model=selected_model,
                litellm_model=litellm_model,
                route_mode="auto" if body.model in policy_cfg.auto_model_ids else "passthrough",
                latency_ms=latency_ms,
                status="ok",
                cache_hit=True,
                cache_layer="local",
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
    )
    kwargs = _completion_kwargs(body)
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
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    latency_ms = (time.perf_counter() - started) * 1000
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
    completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
    actual_cost = completion_cost(response)

    payload = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    payload["model_router"] = _router_meta(
        classification,
        decision,
        cache_hit=False,
        cache_layer=decision.cache_layer if decision else "none",
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
        actual_cost_usd=actual_cost,
        cache_layer=decision.cache_layer if decision else "none",
    )
    return JSONResponse(payload)


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "model_router.gateway:app",
        host=settings.model_router_host,
        port=settings.model_router_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
