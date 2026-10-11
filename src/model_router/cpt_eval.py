"""Lightweight offline CPT-style routing distribution helpers (no GPU / network)."""

from __future__ import annotations

from dataclasses import dataclass

from model_router.classifier import classify_messages
from model_router.config import load_benchmarks, load_models, load_policy
from model_router.policy import SelectionPolicy

# Models treated as "strong" (frontier / premium) vs "cheap" (cost leaders)
STRONG_PREFIXES = (
    "openai/gpt-5.6-sol",
    "openai/gpt-5.6-terra",
    "anthropic/claude-opus",
    "anthropic/claude-sonnet",
)
CHEAP_PREFIXES = (
    "deepseek/",
    "zai/",
    "openai/gpt-5.6-luna",
    "openai/gpt-4o-mini",
    "moonshot/",
    "minimax/",
)


@dataclass(frozen=True)
class PromptCase:
    name: str
    content: str
    tools: list[dict] | None = None
    expect_task: str | None = None


HARNESS_PROMPTS: list[PromptCase] = [
    PromptCase(
        name="code_gen_with_tools",
        content="Write a Python function that merges two sorted lists. Return only the code.",
        tools=[{"type": "function", "function": {"name": "run_terminal"}}],
        expect_task="code_generation",
    ),
    PromptCase(
        name="code_debug_with_tools",
        content="Debug this failing test: AssertionError in test_merge — stack trace attached.",
        tools=[{"type": "function", "function": {"name": "read_file"}}],
        expect_task="code_review_debug",
    ),
    PromptCase(
        name="simple_chat",
        content="Hello — keep it short.",
        expect_task="general_chat",
    ),
    PromptCase(
        name="summarize",
        content="Please summarize this article into key points for a standup.",
        expect_task="summarization",
    ),
    PromptCase(
        name="agent_tool_language",
        content="Use tools to diagnose the failing deploy and search the web for the error.",
        tools=[{"type": "function", "function": {"name": "bash"}}],
        expect_task="tool_use_agent",
    ),
    PromptCase(
        name="ambiguous_tools_only",
        content="What's next?",
        tools=[{"type": "function", "function": {"name": "get_weather"}}],
        expect_task="tool_use_agent",
    ),
    PromptCase(
        name="reasoning",
        content="Solve this leetcode-style problem step by step: prove the complexity of merge sort.",
        expect_task="reasoning_math",
    ),
    PromptCase(
        name="extract_json",
        content="From the text extract JSON with keys name and port only:\n\nService api-gateway listens on port 8080.",
        expect_task="extraction_qa",
    ),
    PromptCase(
        name="extract_factoid",
        content="Context: Prism Router's default listen port is 4000.\nQuestion: What port does Prism listen on by default? Reply with the number only.",
        expect_task="extraction_qa",
    ),
    PromptCase(
        name="creative_haiku",
        content="Write a haiku about routing LLM traffic through a prism. Three lines only.",
        expect_task="creative_writing",
    ),
    PromptCase(
        name="creative_blurb",
        content="Write a playful 4-sentence product blurb for an intelligence-aware model router without using the words 'synergy' or 'revolutionary'.",
        expect_task="creative_writing",
    ),
]


def bucket(model_id: str) -> str:
    for p in STRONG_PREFIXES:
        if model_id.startswith(p) or model_id == p:
            return "strong"
    for p in CHEAP_PREFIXES:
        if model_id.startswith(p):
            return "cheap"
    return "other"


def run_eval() -> list[dict]:
    policy = SelectionPolicy(
        policy=load_policy(),
        benchmarks=load_benchmarks(),
        models=load_models(),
    )
    rows: list[dict] = []
    for case in HARNESS_PROMPTS:
        classification = classify_messages(
            [{"role": "user", "content": case.content}],
            tools=case.tools,
        )
        decision = policy.select(
            task_type=classification.task_type,
            classification_confidence=classification.confidence,
            prompt_text=case.content,
            likely_prefix_reuse=bool(case.tools),
            difficulty=classification.difficulty,
        )
        rows.append(
            {
                "name": case.name,
                "expect_task": case.expect_task,
                "task_type": classification.task_type,
                "difficulty": classification.difficulty,
                "confidence": classification.confidence,
                "signals": classification.signals,
                "selected_model": decision.selected_model,
                "bucket": bucket(decision.selected_model),
                "reason": decision.reason,
                "estimated_cost_usd": decision.estimated_cost_usd,
                "cost_delta_vs_frontier_usd": decision.cost_delta_vs_frontier_usd,
            }
        )
    return rows
