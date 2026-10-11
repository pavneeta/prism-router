"""In-process ``model-router why`` — classify + select without a running gateway."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from model_router.classifier import Classification, classify_messages
from model_router.config import load_benchmarks, load_models, load_policy
from model_router.policy import RoutingDecision, SelectionPolicy


def explain_prompt(
    prompt: str,
    *,
    tools: list[dict[str, Any]] | None = None,
    prior_task: str | None = None,
) -> tuple[Classification, RoutingDecision]:
    messages = [{"role": "user", "content": prompt}]
    classification = classify_messages(messages, tools=tools, prior_task=prior_task)
    policy = SelectionPolicy(
        policy=load_policy(),
        benchmarks=load_benchmarks(),
        models=load_models(),
        require_credentials=False,
    )
    decision = policy.select(
        task_type=classification.task_type,
        classification_confidence=classification.confidence,
        prompt_text=prompt,
        difficulty=classification.difficulty,
    )
    return classification, decision


def format_explain(classification: Classification, decision: RoutingDecision) -> str:
    lines = [
        f"task:       {classification.task_type}",
        f"difficulty: {classification.difficulty}",
        f"confidence: {classification.confidence:.2f}",
        f"model:      {decision.selected_model}",
        f"est $:      {decision.estimated_cost_usd:.6f}",
        f"reason:     {decision.reason}",
        f"signals:    {', '.join(classification.signals)}",
    ]
    return "\n".join(lines)


def explain_as_dict(classification: Classification, decision: RoutingDecision) -> dict[str, Any]:
    return {
        "classification": {
            "task_type": classification.task_type,
            "difficulty": classification.difficulty,
            "confidence": classification.confidence,
            "signals": classification.signals,
        },
        "decision": {
            "selected_model": decision.selected_model,
            "estimated_cost_usd": decision.estimated_cost_usd,
            "reason": decision.reason,
            "min_accuracy": decision.min_accuracy,
            "selected_accuracy": decision.selected_accuracy,
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="model-router why",
        description="Explain how Prism would classify and route a prompt (no server required).",
    )
    ap.add_argument("prompt", nargs="?", help="User prompt to explain")
    ap.add_argument("-f", "--file", help="Read prompt from a file (use - for stdin)")
    ap.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = ap.parse_args(argv)

    prompt = args.prompt
    if args.file:
        if args.file == "-":
            prompt = sys.stdin.read()
        else:
            prompt = open(args.file, encoding="utf-8").read()
    if not prompt or not prompt.strip():
        ap.error("prompt required (positional or --file)")

    classification, decision = explain_prompt(prompt.strip())
    if args.json:
        print(json.dumps(explain_as_dict(classification, decision), indent=2))
    else:
        print(format_explain(classification, decision))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
