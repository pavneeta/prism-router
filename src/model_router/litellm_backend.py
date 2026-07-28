from __future__ import annotations

import copy
from typing import Any

import litellm


async def acompletion(*, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
    """Thin LiteLLM wrapper — Model-Router owns selection; LiteLLM owns providers."""
    return await litellm.acompletion(model=model, messages=messages, **kwargs)


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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None, dict[str, Any]]:
    """Inject provider-appropriate prompt-cache hints for LiteLLM.

    - Anthropic / Claude: ``cache_control`` on system (+ last tool) and
      LiteLLM ``cache_control_injection_points`` as a belt-and-suspenders.
    - OpenAI family: optional ``prompt_cache_key`` (session sticky routing hint).
    """
    if not supports_prompt_caching:
        return messages, tools, {}

    msgs = copy.deepcopy(messages)
    tools_out = copy.deepcopy(tools) if tools else None
    extra: dict[str, Any] = {}

    if _is_anthropic_family(model):
        for msg in msgs:
            if msg.get("role") == "system":
                msg["content"] = _annotate_content_cache_control(msg.get("content", ""))
        if tools_out:
            last = dict(tools_out[-1])
            last["cache_control"] = dict(_ANTHROPIC_CACHE_CONTROL)
            tools_out[-1] = last
        # LiteLLM also accepts injection points (no-op if markers already present)
        extra["cache_control_injection_points"] = [
            {"location": "message", "role": "system"},
        ]
    elif _is_openai_family(model) and session_id:
        extra["prompt_cache_key"] = session_id

    return msgs, tools_out, extra
