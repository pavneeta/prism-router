from __future__ import annotations

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


@dataclass(frozen=True)
class Classification:
    task_type: str
    confidence: float
    signals: list[str]


_CODE_GEN = re.compile(
    r"\b(write|implement|generate|create|scaffold|refactor)\b.*\b(code|function|class|module|script|api)\b"
    r"|\b(python|typescript|javascript|golang|rust|java|sql)\b.*\b(function|class|code)\b"
    r"|```\w*",
    re.I | re.S,
)
_CODE_DEBUG = re.compile(
    r"\b(bug|debug|fix|stack\s*trace|exception|failing\s+test|why\s+doesn'?t|"
    r"TypeError|null\s+deref|security\s+bug|classic\s+python\s+bug)\b",
    re.I,
)
_REASONING = re.compile(
    r"\b(prove|theorem|derive|optimize|complexity|step[- ]by[- ]step|math|equation|leetcode)\b"
    r"|\b(how\s+many|probability|mod\b|average\s+speed|combinat|fraction|Answer:|"
    r"discounted|final\s+price|altogether)\b"
    r"|\b(\d+\s*(km|miles|friends|clips|dollars|%|percent))\b",
    re.I,
)
_SUMMARY = re.compile(
    r"\b(summarize|summary|tl;dr|tldr|condense|key\s+points|executive\s+summary|"
    r"in\s+exactly\s+\d+\s+sentences|in\s+\d+\s+bullets|compress\s+this|"
    r"\d+-bullet)\b",
    re.I,
)
_EXTRACT = re.compile(
    r"\b(extract|parse|find\s+all|according\s+to\s+the\s+(doc|text|passage)|"
    r"reply\s+with\s+the\s+number\s+only|json\s+array|json\s+with\s+keys)\b",
    re.I,
)
_CREATIVE = re.compile(
    r"\b(poem|story|lyrics|novel|screenplay|creative\s+writing|haiku|dialogue|metaphor)\b",
    re.I,
)
_TOOLISH = re.compile(
    r"\b(use\s+tools?|function\s+call|call\s+the\s+api|kubectl_|browse|search\s+the\s+web|"
    r"tool\s+calls?)\b",
    re.I,
)

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


def _classify_content(text: str) -> Classification:
    """Classify from message content only (no tools override)."""
    signals: list[str] = []

    if _TOOLISH.search(text):
        signals.append("tool_language")
        return Classification("tool_use_agent", 0.75, signals)

    if _CODE_DEBUG.search(text):
        signals.append("debug_language")
        return Classification("code_review_debug", 0.8, signals)

    if _CODE_GEN.search(text):
        signals.append("code_generation_language")
        return Classification("code_generation", 0.8, signals)

    if _REASONING.search(text):
        signals.append("reasoning_language")
        return Classification("reasoning_math", 0.75, signals)

    if _SUMMARY.search(text):
        signals.append("summarization_language")
        return Classification("summarization", 0.85, signals)

    if _EXTRACT.search(text):
        signals.append("extraction_language")
        return Classification("extraction_qa", 0.7, signals)

    if _CREATIVE.search(text):
        signals.append("creative_language")
        return Classification("creative_writing", 0.8, signals)

    signals.append("default_chat")
    return Classification("general_chat", 0.55, signals)


def classify_messages(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
) -> Classification:
    """Heuristic task classifier — fast path for MVP (<5ms typical).

    Tools present is a *signal*, not a hard override. Agent harnesses attach
    tools every turn; coding / debug prompts must still classify as code tasks.
    """
    text = _message_text(messages)
    content = _classify_content(text)
    signals = list(content.signals)

    if not tools:
        return content

    signals.append("tools_present")

    # Content already points at tools/agents — boost confidence
    if content.task_type == "tool_use_agent":
        return Classification("tool_use_agent", max(content.confidence, 0.9), signals)

    # Strong content match wins (coding prompts with tools stay code_*)
    if content.task_type in _STRONG_CONTENT_TYPES:
        return Classification(content.task_type, content.confidence, signals)

    # Weak / ambiguous content (general_chat): nudge toward tool_use_agent
    signals.append("tools_nudge_ambiguous")
    return Classification("tool_use_agent", 0.7, signals)
