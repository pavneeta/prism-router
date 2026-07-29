"""Shadow-eval mirror: customer model (primary) + auto route (shadow).

When enabled, passthrough chat completions still return the customer-configured
model response. Concurrently Prism selects via auto and completes that path,
appending both outputs to a JSONL file for offline eval. Optionally an LLM
judge (small model) scores the pair.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from model_router.classifier import Classification
from model_router.config import Settings, get_selection_policy, load_policy
from model_router.litellm_backend import acompletion, apply_provider_cache_hints
from model_router.policy import RoutingDecision, estimate_input_tokens
from model_router.prompt_cache import get_prompt_cache
from model_router.telemetry import now_ts

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()

_JUDGE_SYSTEM = """You are an evaluation judge comparing two assistant replies to the same user request.
Score which answer is better for the stated task. Prefer correctness, completeness, and clarity.
Respond with ONLY a single JSON object (no markdown):
{"winner":"primary"|"auto"|"tie","score":0.0-1.0,"rationale":"one short sentence"}
score is confidence that the winner is better (0.5 for tie)."""


def should_mirror(
    settings: Settings,
    *,
    requested_model: str,
    route_mode: str,
    stream: bool,
) -> bool:
    """Mirror only for non-stream passthrough when the client did not ask for auto."""
    if not settings.model_router_mirror_mode:
        return False
    if stream:
        return False
    if route_mode == "auto":
        return False
    policy = load_policy()
    if requested_model in policy.auto_model_ids or requested_model.endswith("/auto"):
        return False
    return True


def shadow_select(
    *,
    classification: Classification,
    prompt_text: str,
    session_id: str | None,
    likely_prefix_reuse: bool,
) -> RoutingDecision:
    """Select the auto model without re-entering gateway `_route` (no session writes)."""
    policy_cfg = load_policy()
    cache = get_prompt_cache()
    affinity = cache.get_affinity(session_id) if policy_cfg.prompt_cache_enabled else None
    return get_selection_policy().select(
        task_type=classification.task_type,
        classification_confidence=classification.confidence,
        prompt_text=prompt_text,
        session_affinity=affinity,
        likely_prefix_reuse=likely_prefix_reuse,
    )


def _usage_dict(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if isinstance(usage, dict):
        return usage
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def _content_from_response(response: Any) -> str | None:
    try:
        payload = response.model_dump() if hasattr(response, "model_dump") else dict(response)
        choices = payload.get("choices") or []
        if not choices:
            return None
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        return content if isinstance(content, str) else None
    except Exception:  # noqa: BLE001
        return None


def append_mirror_record(path: Path, record: dict[str, Any]) -> None:
    """Append mirror JSONL. Raises OSError on failure (caller logs and continues)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, default=str) + "\n"
    with _write_lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)


def _parse_judge_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


async def judge_pair(
    *,
    judge_model: str,
    task_type: str,
    user_prompt: str,
    primary_content: str,
    auto_content: str,
    primary_model: str,
    auto_model: str,
) -> dict[str, Any]:
    """LLM-as-judge with a small model; returns winner/score/rationale."""
    user = (
        f"Task type: {task_type}\n"
        f"User request:\n{user_prompt[:6000]}\n\n"
        f"Reply A (primary / customer model={primary_model}):\n{primary_content[:8000]}\n\n"
        f"Reply B (auto / router model={auto_model}):\n{auto_content[:8000]}\n"
    )
    try:
        response = await acompletion(
            model=judge_model,
            messages=[
                {"role": "system", "content": _JUDGE_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0,
            max_tokens=200,
            num_retries=0,
            timeout=45,
        )
        raw = _content_from_response(response) or ""
        parsed = _parse_judge_json(raw) or {}
        winner = str(parsed.get("winner") or "tie").lower()
        if winner not in {"primary", "auto", "tie"}:
            winner = "tie"
        try:
            score = float(parsed.get("score", 0.5))
        except (TypeError, ValueError):
            score = 0.5
        score = max(0.0, min(1.0, score))
        return {
            "winner": winner,
            "score": score,
            "rationale": str(parsed.get("rationale") or raw)[:500],
            "judge_model": judge_model,
            "raw": raw[:1000] if not parsed else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "winner": "tie",
            "score": 0.0,
            "rationale": f"judge_error: {exc}",
            "judge_model": judge_model,
            "error": str(exc),
        }


async def _complete_shadow(
    *,
    decision: RoutingDecision,
    raw_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    completion_kwargs: dict[str, Any],
    session_id: str | None,
) -> tuple[dict[str, Any], str | None]:
    policy_cfg = load_policy()
    messages, tools_out, cache_extra = apply_provider_cache_hints(
        model=decision.litellm_model,
        messages=raw_messages,
        tools=tools,
        supports_prompt_caching=decision.supports_prompt_caching and policy_cfg.prompt_cache_enabled,
        session_id=session_id,
        fireworks_hide_thinking=policy_cfg.fireworks_hide_thinking,
    )
    call_kwargs = dict(completion_kwargs)
    # Shadow completions should not inherit primary GPT-5 temperature stripping quirks
    # beyond what _completion_kwargs already applied for the primary litellm id —
    # re-drop temperature for gpt-5 shadow targets.
    if "gpt-5" in decision.litellm_model.lower():
        call_kwargs.pop("temperature", None)
    call_kwargs.update(cache_extra)
    if tools_out is not None:
        call_kwargs["tools"] = tools_out
    response = await acompletion(
        model=decision.litellm_model,
        messages=messages,
        **call_kwargs,
    )
    content = _content_from_response(response)
    side = {
        "selected_model": decision.selected_model,
        "litellm_model": decision.litellm_model,
        "reason": decision.reason,
        "selected_accuracy": decision.selected_accuracy,
        "estimated_cost_usd": decision.estimated_cost_usd,
        "content": content,
        "usage": _usage_dict(response),
        "status": "ok",
    }
    return side, content


async def run_mirror_eval(
    *,
    settings: Settings,
    request_id: str,
    session_id: str | None,
    requested_model: str,
    primary_litellm_model: str,
    primary_content: str | None,
    primary_usage: dict[str, Any] | None,
    classification: Classification,
    prompt_text: str,
    raw_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    completion_kwargs: dict[str, Any],
    likely_prefix_reuse: bool,
    decision_payload_fn: Any,
) -> None:
    """Background: auto completion (+ optional judge) → JSONL. Never raises to caller."""
    started = now_ts()
    record: dict[str, Any] = {
        "ts": started,
        "request_id": request_id,
        "session_id": session_id,
        "task_type": classification.task_type,
        "classification_confidence": classification.confidence,
        "classification_signals": list(classification.signals),
        "prompt_preview": prompt_text[:2000],
        "prompt_tokens_est": estimate_input_tokens(prompt_text),
        "primary": {
            "requested_model": requested_model,
            "litellm_model": primary_litellm_model,
            "content": primary_content,
            "usage": primary_usage,
            "status": "ok",
        },
        "auto": None,
        "judge": None,
    }
    try:
        decision = shadow_select(
            classification=classification,
            prompt_text=prompt_text,
            session_id=session_id,
            likely_prefix_reuse=likely_prefix_reuse,
        )
        record["auto_decision"] = decision_payload_fn(decision)

        # Skip duplicate spend if auto selected the same deployment
        if decision.litellm_model == primary_litellm_model:
            record["auto"] = {
                "selected_model": decision.selected_model,
                "litellm_model": decision.litellm_model,
                "reason": decision.reason,
                "selected_accuracy": decision.selected_accuracy,
                "estimated_cost_usd": decision.estimated_cost_usd,
                "content": primary_content,
                "usage": primary_usage,
                "status": "skipped_same_model",
            }
        else:
            auto_side, auto_content = await _complete_shadow(
                decision=decision,
                raw_messages=raw_messages,
                tools=tools,
                completion_kwargs=completion_kwargs,
                session_id=session_id,
            )
            record["auto"] = auto_side

            if (
                settings.model_router_mirror_judge
                and primary_content
                and auto_content
            ):
                record["judge"] = await judge_pair(
                    judge_model=settings.model_router_mirror_judge_model,
                    task_type=classification.task_type,
                    user_prompt=prompt_text,
                    primary_content=primary_content,
                    auto_content=auto_content,
                    primary_model=requested_model,
                    auto_model=decision.selected_model,
                )
    except Exception as exc:  # noqa: BLE001
        logger.exception("mirror eval failed request_id=%s", request_id)
        record["auto"] = {"status": "error", "error": str(exc)}
    finally:
        record["mirror_latency_ms"] = (now_ts() - started) * 1000
        try:
            append_mirror_record(Path(settings.model_router_mirror_path), record)
        except Exception:  # noqa: BLE001
            logger.exception("failed to write mirror record")


def schedule_mirror_eval(**kwargs: Any) -> None:
    """Fire-and-forget background task (does not delay the client response)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("mirror: no running loop; skipping")
        return
    task = loop.create_task(run_mirror_eval(**kwargs))

    def _done(t: asyncio.Task[None]) -> None:
        try:
            t.result()
        except Exception:  # noqa: BLE001
            logger.exception("mirror background task crashed")

    task.add_done_callback(_done)
