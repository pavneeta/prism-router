from __future__ import annotations

import asyncio
import copy
import os
from typing import Any

import litellm

# Ignore provider-unsupported kwargs (e.g. Anthropic temperature quirks)
litellm.drop_params = True
litellm.num_retries = 0
litellm.request_timeout = 60


async def acompletion(*, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
    """Thin LiteLLM wrapper — Model-Router owns selection; LiteLLM owns providers."""
    # Bound provider waits so a hung upstream surfaces as 502 instead of stalling the gateway.
    kwargs.setdefault("timeout", 60)
    kwargs.setdefault("num_retries", 0)
    try:
        return await asyncio.wait_for(
            litellm.acompletion(model=model, messages=messages, **kwargs),
            timeout=75,
        )
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"provider timed out for model={model}") from exc


def completion_cost(response: Any) -> float | None:
    try:
        return float(litellm.completion_cost(completion_response=response))
    except Exception:
        return None


_ANTHROPIC_CACHE_CONTROL = {"type": "ephemeral"}


def _is_anthropic_family(model: str) -> bool:
    lower = model.lower()
    return lower.startswith("anthropic/") or "claude" in lower


def _is_openai_family(model: str) -> bool:
    lower = model.lower()
    return lower.startswith("openai/") or lower.startswith("azure/")


def _is_fireworks_family(model: str) -> bool:
    lower = model.lower()
    return lower.startswith("fireworks_ai/") or lower.startswith("fireworks/")


def provider_type(model: str) -> str:
    """Normalize LiteLLM / catalog model id to a provider family label."""
    lower = (model or "").lower()
    if _is_anthropic_family(lower):
        return "anthropic"
    if _is_openai_family(lower):
        return "openai"
    if _is_fireworks_family(lower):
        return "fireworks"
    if lower.startswith("gemini/") or lower.startswith("vertex_ai/"):
        return "google"
    if lower.startswith("together_ai/") or lower.startswith("together/"):
        return "together"
    if "/" in lower:
        return lower.split("/", 1)[0] or "unknown"
    return "unknown"


_PROVIDER_CREDENTIALS: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "fireworks": ("FIREWORKS_API_KEY", "FIREWORKS_AI_API_KEY"),
    "together": ("TOGETHER_API_KEY",),
    "google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "groq": ("GROQ_API_KEY",),
}


def provider_credential_available(
    model: str,
    *,
    environ: dict[str, str] | None = None,
) -> bool:
    """Return whether the provider credential required by ``model`` exists.

    Unknown/custom providers are fail-closed for automatic routing. Explicit
    passthrough still reaches LiteLLM and can use its provider-specific auth.
    """
    env = os.environ if environ is None else environ
    provider = provider_type(model)
    names = _PROVIDER_CREDENTIALS.get(provider)
    if not names:
        return False
    return any(bool((env.get(name) or "").strip()) for name in names)


def _as_usage_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        dumped = usage.model_dump()
        return dumped if isinstance(dumped, dict) else None
    if isinstance(usage, dict):
        return usage
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
        "prompt_tokens_details": getattr(usage, "prompt_tokens_details", None),
    }


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_cached_tokens(usage: dict[str, Any]) -> int | None:
    """Best-effort provider cached / cache-read token count."""
    details = usage.get("prompt_tokens_details")
    if details is not None:
        if hasattr(details, "model_dump"):
            details = details.model_dump()
        if isinstance(details, dict):
            cached = _coerce_int(details.get("cached_tokens"))
            if cached is not None:
                return cached
        else:
            cached = _coerce_int(getattr(details, "cached_tokens", None))
            if cached is not None:
                return cached

    for key in (
        "cached_tokens",
        "cache_read_input_tokens",
        "cached_prompt_tokens",
        "cached-prompt-tokens",
    ):
        cached = _coerce_int(usage.get(key))
        if cached is not None:
            return cached

    # Nested provider extras (Fireworks perf metrics, etc.)
    for nest_key in ("prompt_tokens_details", "completion_tokens_details", "extra"):
        nested = usage.get(nest_key)
        if isinstance(nested, dict):
            for key in ("cached_tokens", "cached_prompt_tokens", "cached-prompt-tokens"):
                cached = _coerce_int(nested.get(key))
                if cached is not None:
                    return cached
    return None


def extract_token_usage(usage: Any) -> tuple[int | None, int | None, int | None]:
    """Return (prompt_tokens, completion_tokens, cached_tokens) from a usage object."""
    data = _as_usage_dict(usage)
    if not data:
        return None, None, None
    prompt = _coerce_int(data.get("prompt_tokens"))
    if prompt is None:
        prompt = _coerce_int(data.get("input_tokens"))
    completion = _coerce_int(data.get("completion_tokens"))
    if completion is None:
        completion = _coerce_int(data.get("output_tokens"))
    cached = _extract_cached_tokens(data)
    return prompt, completion, cached


def _annotate_content_cache_control(content: Any) -> Any:
    """Attach Anthropic cache_control to a message content value."""
    if isinstance(content, str):
        return [
            {
                "type": "text",
                "text": content,
                "cache_control": dict(_ANTHROPIC_CACHE_CONTROL),
            }
        ]
    if isinstance(content, list):
        blocks = [copy.deepcopy(b) for b in content]
        if not blocks:
            return blocks
        last = blocks[-1]
        if isinstance(last, dict):
            last = dict(last)
            last["cache_control"] = dict(_ANTHROPIC_CACHE_CONTROL)
            blocks[-1] = last
        return blocks
    if isinstance(content, dict):
        block = copy.deepcopy(content)
        block["cache_control"] = dict(_ANTHROPIC_CACHE_CONTROL)
        return block
    return content


def apply_provider_cache_hints(
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    supports_prompt_caching: bool,
    session_id: str | None = None,
    fireworks_hide_thinking: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None, dict[str, Any]]:
    """Inject provider-appropriate prompt-cache / response hints for LiteLLM.

    - Anthropic / Claude: ``cache_control`` on system (+ last tool) and
      LiteLLM ``cache_control_injection_points`` as a belt-and-suspenders.
    - OpenAI family: optional ``prompt_cache_key`` (session sticky routing hint).
    - Fireworks: caching is on by default; pass ``prompt_cache_key`` plus
      ``x-session-affinity`` so multi-replica serverless sticks to one KV
      cache. ``perf_metrics_in_response`` surfaces ``cached-prompt-tokens``.
      When ``fireworks_hide_thinking``, send ``thinking={"type":"disabled"}``
      so CoT is not dumped into visible ``content`` (Fireworks rejects
      combining this with ``reasoning_effort``).
    """
    msgs = copy.deepcopy(messages)
    tools_out = copy.deepcopy(tools) if tools else None
    extra: dict[str, Any] = {}

    if supports_prompt_caching:
        if _is_anthropic_family(model):
            for msg in msgs:
                if msg.get("role") == "system":
                    msg["content"] = _annotate_content_cache_control(msg.get("content", ""))
            if tools_out:
                last = dict(tools_out[-1])
                last["cache_control"] = dict(_ANTHROPIC_CACHE_CONTROL)
                tools_out[-1] = last
            extra["cache_control_injection_points"] = [
                {"location": "message", "role": "system"},
            ]
        elif _is_openai_family(model) and session_id:
            extra["prompt_cache_key"] = session_id
        elif _is_fireworks_family(model) and session_id:
            # Preferred Fireworks sticky key (takes priority over ``user``).
            # https://docs.fireworks.ai/guides/prompt-caching
            extra["prompt_cache_key"] = session_id
            headers = dict(extra.get("extra_headers") or {})
            headers.setdefault("x-session-affinity", session_id)
            extra["extra_headers"] = headers
            # Body metrics (headers alone are dedicated-deployment oriented).
            extra["perf_metrics_in_response"] = True

    if fireworks_hide_thinking and _is_fireworks_family(model):
        # Fireworks chat completions: only one of thinking / reasoning_effort.
        extra["thinking"] = {"type": "disabled"}

    return msgs, tools_out, extra
