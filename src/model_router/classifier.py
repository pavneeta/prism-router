from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any


TASK_TYPES = (
    "code_generation",
    "code_review_debug",
    "reasoning_math",
    "summarization",
    "extraction_qa",
    "tool_use_agent",
    "creative_writing",
    "general_chat",
)

DIFFICULTIES = ("easy", "hard")

_HARD_FLOOR_TASKS = frozenset(
    {"code_generation", "code_review_debug", "tool_use_agent"}
)


@dataclass(frozen=True)
class Classification:
    task_type: str
    confidence: float
    signals: list[str]
    difficulty: str = "easy"


# Content classes strong enough that tools_present must not override them
_STRONG_CONTENT_TYPES = frozenset(
    {
        "code_generation",
        "code_review_debug",
        "reasoning_math",
        "summarization",
        "extraction_qa",
        "creative_writing",
        "tool_use_agent",
    }
)

_CODE_FENCE = re.compile(r"```[\w+-]*", re.I)
_CODE_FENCE_BODY = re.compile(r"```[\w+-]*\n(.{200,})", re.S)
_CODE_GEN = re.compile(
    r"\b(write|implement|generate|create|scaffold|refactor)\b.*\b("
    r"code|function|class|module|script|api|method)\b"
    r"|\bwrite\s+(a\s+)?(python|typescript|javascript|golang|rust|java|sql)\b"
    r"|\b(python|typescript|javascript|golang|rust|java|sql)\b.*\b("
    r"function|class|code|def\b|impl)\b"
    r"|return only the (function|class|code|module)",
    re.I | re.S,
)
_CODE_DEBUG = re.compile(
    r"\b(bug|debug|fix|stack\s*trace|exception|failing\s+test|why\s+doesn'?t|"
    r"TypeError|null\s+deref|security\s+bug|classic\s+python\s+bug|"
    r"off[- ]by[- ]one|vulnerability)\b",
    re.I,
)
_REASONING = re.compile(
    r"\b(prove|theorem|derive|optimize|complexity|step[- ]by[- ]step|math|"
    r"equation|leetcode)\b"
    r"|\b(probability|mod\b|average\s+speed|combinat|fraction|Answer:|"
    r"discounted|final\s+price|altogether)\b"
    r"|\b(\d+\s*(km|miles|friends|clips|dollars|%|percent))\b",
    re.I,
)
_BARE_HOW_MANY = re.compile(r"\bhow\s+many\b", re.I)
_SUMMARY = re.compile(
    r"\b(summarize|summary|tl;dr|tldr|condense|key\s+points|executive\s+summary|"
    r"in\s+exactly\s+\d+\s+sentences|in\s+\d+\s+bullets|compress\s+this|"
    r"\d+-bullet)\b",
    re.I,
)
_EXTRACT = re.compile(
    r"\b(extract|parse|find\s+all|according\s+to|"
    r"from\s+the\s+(text|context|passage|doc)|"
    r"reply\s+with\s+the\s+number\s+only|number\s+only|"
    r"json\s+array|json\s+with\s+keys|as\s+json|"
    r"answer\s+yes\s+or\s+no|"
    r"list\s+the\s+\w+\s+mentioned)\b",
    re.I,
)
_FACTOID = re.compile(
    r"\b(what\s+(port|version|date|name|id|value)|"
    r"context:\s|"
    r"question:\s|"
    r"reply\s+with\s+(the\s+)?(number|json|yes|no)|"
    r"keys\s+name\s+and)\b",
    re.I,
)
_CREATIVE = re.compile(
    r"\b(poem|story|lyrics|novel|screenplay|creative\s+writing|haiku|"
    r"dialogue|metaphor|limerick|sonnet|slogan|verse|"
    r"product\s+blurb|warning\s+label|playful|"
    r"short\s+dialogue|three\s+lines\s+only)\b",
    re.I,
)
_TOOLISH = re.compile(
    r"\b(use\s+tools?|function\s+call|call\s+the\s+api|kubectl_|browse|"
    r"search\s+the\s+web|tool\s+calls?|prefer\s+tool\s+calls)\b",
    re.I,
)
_K8S_OPS = re.compile(
    r"\b(kubectl|helm|kubelet|crashloopbackoff|oomkilled|"
    r"namespace|ingress|replica(?:set)?s?|rollout|"
    r"describe\s+pod|get\s+logs|pod\s+\w+|deploy(?:ment)?s?)\b",
    re.I,
)
_HARD_MARKERS = re.compile(
    r"\b(lru|lrucache|least[- ]recently[- ]used|debounce|running[- _]?median|"
    r"async(?:hronous)?|await|race[- ]condition|deadlock|"
    r"multi[- ]tool|orchestrat|distributed|consensus|"
    r"thread[- ]safe|concurrent|multi[- ]threaded)\b"
    r"|O\(\s*1\s*\)",
    re.I,
)
_SHORT_FOLLOWUP = re.compile(
    r"^(ok|okay|continue|go on|yes|yep|thanks|fix that|do it|again|"
    r"same|more|next|please)\.?$",
    re.I,
)


def _message_text(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
    return "\n".join(parts)


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if str(msg.get("role", "")).lower() != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return "\n".join(parts)
    return ""


def _length_bucket(n: int) -> str:
    if n < 240:
        return "short"
    if n < 1500:
        return "medium"
    return "long"


def _infer_difficulty(
    text: str,
    *,
    task_type: str,
    tools: list[dict[str, Any]] | None,
    signals: list[str],
) -> str:
    if task_type not in _HARD_FLOOR_TASKS:
        return "easy"
    if _HARD_MARKERS.search(text):
        signals.append("difficulty_hard_marker")
        return "hard"
    if tools and len(tools) >= 3 and (
        "tool_language" in signals or "k8s_ops" in signals or task_type == "tool_use_agent"
    ):
        signals.append("difficulty_multi_tool")
        return "hard"
    if len(text) >= 2000:
        signals.append("difficulty_long_prompt")
        return "hard"
    if task_type.startswith("code") and _CODE_FENCE_BODY.search(text):
        signals.append("difficulty_complex_fence")
        return "hard"
    return "easy"


def _score_text(text: str) -> tuple[dict[str, float], list[str]]:
    scores = {t: 0.0 for t in TASK_TYPES}
    signals: list[str] = []

    if _TOOLISH.search(text):
        scores["tool_use_agent"] += 3.0
        signals.append("tool_language")
    if _K8S_OPS.search(text):
        scores["tool_use_agent"] += 2.2
        signals.append("k8s_ops")
    if _CODE_DEBUG.search(text):
        scores["code_review_debug"] += 3.2
        signals.append("debug_language")
    if _CODE_GEN.search(text):
        scores["code_generation"] += 3.0
        signals.append("code_generation_language")
    if _CODE_FENCE.search(text):
        scores["code_generation"] += 0.8
        scores["code_review_debug"] += 0.6
        signals.append("code_fence")

    extract_hit = bool(_EXTRACT.search(text) or _FACTOID.search(text))
    if extract_hit:
        scores["extraction_qa"] += 3.1
        signals.append("extraction_language")
        if _FACTOID.search(text):
            signals.append("factoid")

    if _REASONING.search(text):
        scores["reasoning_math"] += 2.6
        signals.append("reasoning_language")
    if _BARE_HOW_MANY.search(text) and not extract_hit:
        scores["reasoning_math"] += 2.2
        signals.append("how_many")
    elif _BARE_HOW_MANY.search(text) and extract_hit:
        # Grounded "how many … number only" is extraction, not contest math.
        scores["extraction_qa"] += 1.2
        signals.append("how_many_grounded")

    if _SUMMARY.search(text):
        scores["summarization"] += 3.0
        signals.append("summarization_language")
    if _CREATIVE.search(text):
        scores["creative_writing"] += 2.8
        signals.append("creative_language")

    return scores, signals


def _pick(scores: dict[str, float], signals: list[str]) -> tuple[str, float]:
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_type, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if best <= 0:
        signals.append("default_chat")
        return "general_chat", 0.55
    margin = best - second
    confidence = min(0.95, 0.58 + 0.08 * best + 0.12 * min(margin, 2.5))
    return best_type, round(confidence, 4)


def _classify_content(text: str) -> Classification:
    scores, signals = _score_text(text)
    task_type, confidence = _pick(scores, signals)
    return Classification(task_type, confidence, signals)


def _heuristic_second_pass(text: str, first: Classification) -> Classification:
    """Low-confidence rescue for known miss classes (extract / creative)."""
    if first.confidence >= 0.7 and first.task_type != "general_chat":
        return first
    signals = list(first.signals)
    if first.task_type == "general_chat" or first.confidence < 0.7:
        if _EXTRACT.search(text) or _FACTOID.search(text):
            signals.append("second_pass_extract")
            return Classification("extraction_qa", max(first.confidence, 0.78), signals)
        if _CREATIVE.search(text):
            signals.append("second_pass_creative")
            return Classification("creative_writing", max(first.confidence, 0.78), signals)
        if _K8S_OPS.search(text):
            signals.append("second_pass_k8s")
            return Classification("tool_use_agent", max(first.confidence, 0.76), signals)
    return first


def _llm_classify_enabled() -> bool:
    raw = (os.environ.get("MODEL_ROUTER_LLM_CLASSIFY") or "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _optional_llm_classify(text: str, heuristic: Classification) -> Classification:
    """Optional structured classify when confidence is low. Fail-soft."""
    if heuristic.confidence >= 0.7 or not _llm_classify_enabled():
        return heuristic
    try:
        import json

        from litellm import completion

        model = (
            os.environ.get("MODEL_ROUTER_LLM_CLASSIFY_MODEL") or "openai/gpt-4o-mini"
        ).strip()
        timeout = float(os.environ.get("MODEL_ROUTER_LLM_CLASSIFY_TIMEOUT") or "2.0")
        prompt = (
            "Classify the user prompt into exactly one task_type and difficulty.\n"
            f"task_type must be one of: {', '.join(TASK_TYPES)}\n"
            "difficulty must be easy or hard.\n"
            "Reply with JSON only: "
            '{"task_type":"...","difficulty":"easy|hard","confidence":0.0}\n\n'
            f"Prompt:\n{text[:4000]}"
        )
        resp = completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=80,
            timeout=timeout,
        )
        content = str(resp.choices[0].message.content or "")
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            return heuristic
        data = json.loads(content[start : end + 1])
        task = str(data.get("task_type") or "")
        if task not in TASK_TYPES:
            return heuristic
        diff = str(data.get("difficulty") or heuristic.difficulty)
        if diff not in DIFFICULTIES:
            diff = heuristic.difficulty
        conf = float(data.get("confidence") or 0.75)
        signals = list(heuristic.signals) + ["llm_classify"]
        return Classification(task, min(0.95, max(0.5, conf)), signals, difficulty=diff)
    except Exception:
        return heuristic


def classify_messages(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    prior_task: str | None = None,
) -> Classification:
    """Heuristic task classifier — fast path for MVP (<5ms typical).

    Tools present is a *signal*, not a hard override. Agent harnesses attach
    tools every turn; coding / debug prompts must still classify as code tasks.
    Multi-turn: last user message is the primary text; ``prior_task`` is a hint.
    """
    full = _message_text(messages)
    last = _last_user_text(messages) or full
    text = last or full
    signals_extra: list[str] = []

    if last and full and last != full:
        signals_extra.append("multi_turn_last_user")
    if prior_task:
        signals_extra.append(f"prior_task:{prior_task}")
    if last and _SHORT_FOLLOWUP.match(last.strip()) and prior_task:
        signals_extra.append("short_followup")

    content = _heuristic_second_pass(text, _classify_content(text))
    content = _optional_llm_classify(text, content)
    signals = list(content.signals) + signals_extra
    signals.append(f"prompt_len:{_length_bucket(len(full or text))}")

    if tools:
        signals.append("tools_present")
        if content.task_type == "tool_use_agent":
            task_type, confidence = "tool_use_agent", max(content.confidence, 0.9)
        elif content.task_type in _STRONG_CONTENT_TYPES:
            task_type, confidence = content.task_type, content.confidence
        else:
            signals.append("tools_nudge_ambiguous")
            task_type, confidence = "tool_use_agent", 0.7
    else:
        task_type, confidence = content.task_type, content.confidence

    difficulty = _infer_difficulty(
        full or text, task_type=task_type, tools=tools, signals=signals
    )
    return Classification(task_type, confidence, signals, difficulty=difficulty)
