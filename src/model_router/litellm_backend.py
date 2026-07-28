from __future__ import annotations

import copy
from typing import Any

import litellm

# Ignore provider-unsupported kwargs (e.g. Anthropic temperature quirks)
litellm.drop_params = True


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


def _is_fireworks_family(model: str) -> bool:
    lower = model.lower()
    return lower.startswith("fireworks_ai/") or lower.startswith("fireworks/")


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
    - Fireworks: when ``fireworks_hide_thinking``, send
      ``reasoning_effort="none"`` and ``thinking={"type":"disabled"}`` so CoT
      is not dumped into visible ``content`` (Fireworks chat completions API).
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

    if fireworks_hide_thinking and _is_fireworks_family(model):
        # Equivalent knobs per Fireworks docs; send both for wider model coverage.
        extra["reasoning_effort"] = "none"
        extra["thinking"] = {"type": "disabled"}

    return msgs, tools_out, extra
