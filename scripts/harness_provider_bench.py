#!/usr/bin/env python3
"""Cross-harness × provider family benchmark against Prism Router.

Exercises OpenCode-, Hermes-, and HolmesGPT-shaped clients against:
  - auto routing
  - forced OpenAI / Anthropic / open (Fireworks) models

Modes:
  --dry-run   Force MODEL_ROUTER_DRY_RUN semantics by calling /v1/router/explain
              for selection, then /v1/chat/completions (works with dry gateway).
  --live      Hit chat completions for real provider latency/cost (needs keys).

Usage:
  MODEL_ROUTER_DRY_RUN=true model-router   # terminal 1
  python scripts/harness_provider_bench.py --dry-run -o logs/harness_provider_bench.md
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("PRISM_BASE", "http://127.0.0.1:4000")

# Provider families → concrete catalog / passthrough ids
PROVIDER_MODES: dict[str, dict[str, str]] = {
    "auto": {"model": "auto", "family": "router"},
    "openai": {"model": "openai/gpt-4o-mini", "family": "openai"},
    "anthropic": {"model": "anthropic/claude-sonnet-5", "family": "anthropic"},
    "open": {"model": "deepseek/deepseek-v4-pro", "family": "open"},
}

HARNESSES: dict[str, dict[str, Any]] = {
    "opencode": {
        "auto_model": "model-router/auto",
        "session": "bench-opencode",
        "headers_extra": {},
        "use_tools_on_agent": False,
    },
    "hermes": {
        "auto_model": "auto",
        "session": "bench-hermes",
        "headers_extra": {},
        "use_tools_on_agent": False,
    },
    "holmesgpt": {
        "auto_model": "openai/auto",
        "session": "bench-holmesgpt",
        "headers_extra": {},
        "use_tools_on_agent": True,  # Holmes requires function calling
    },
}

PROMPTS: list[dict[str, Any]] = [
    {
        "id": "chat",
        "content": "In one short sentence, say hello to the on-call engineer.",
        "tools": None,
    },
    {
        "id": "code",
        "content": "Write a Python function that merges two sorted lists. Return only the function.",
        "tools": None,
    },
    {
        "id": "agent",
        "content": "Use tools to diagnose CrashLoopBackOff on the payments pod in namespace prod.",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "kubectl_logs",
                    "description": "Fetch Kubernetes pod logs",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pod": {"type": "string"},
                            "namespace": {"type": "string"},
                        },
                    },
                },
            }
        ],
    },
]


@dataclass
class Trial:
    harness: str
    provider_mode: str
    prompt_id: str
    requested_model: str
    ok: bool
    latency_ms: float
    selected_model: str | None = None
    litellm_model: str | None = None
    task_type: str | None = None
    estimated_cost_usd: float | None = None
    actual_cost_usd: float | None = None
    content_preview: str = ""
    error: str = ""
    family: str = ""


@dataclass
class Report:
    generated_at: str
    base: str
    dry_run: bool
    trials: list[Trial] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"# Harness × provider bench",
            "",
            f"- Generated (UTC): `{self.generated_at}`",
            f"- Gateway: `{self.base}`",
            f"- Mode: `{'dry-run / explain+chat' if self.dry_run else 'live chat'}`",
            f"- Trials: **{len(self.trials)}** · OK: **{sum(1 for t in self.trials if t.ok)}**",
            "",
            "## Matrix results",
            "",
            "| Harness | Provider | Prompt | OK | Task | Selected | Est $ | Latency ms |",
            "| --- | --- | --- | --- | --- | --- | ---: | ---: |",
        ]
        for t in self.trials:
            est = f"{t.estimated_cost_usd:.6f}" if t.estimated_cost_usd is not None else "—"
            lines.append(
                f"| {t.harness} | {t.provider_mode} | {t.prompt_id} | "
                f"{'✓' if t.ok else '✗'} | {t.task_type or '—'} | "
                f"`{t.selected_model or '—'}` | {est} | {t.latency_ms:.0f} |"
            )

        lines.extend(["", "## By harness × provider (success / mean latency)", ""])
        lines.append("| Harness | Provider | n OK | mean ms | mean est $ |")
        lines.append("| --- | --- | ---: | ---: | ---: |")
        for harness in HARNESSES:
            for mode in PROVIDER_MODES:
                subset = [
                    t
                    for t in self.trials
                    if t.harness == harness and t.provider_mode == mode and t.ok
                ]
                if not subset:
                    lines.append(f"| {harness} | {mode} | 0 | — | — |")
                    continue
                mean_ms = statistics.mean(t.latency_ms for t in subset)
                costs = [t.estimated_cost_usd for t in subset if t.estimated_cost_usd is not None]
                mean_cost = statistics.mean(costs) if costs else None
                cost_s = f"{mean_cost:.6f}" if mean_cost is not None else "—"
                lines.append(
                    f"| {harness} | {mode} | {len(subset)} | {mean_ms:.0f} | {cost_s} |"
                )

        fails = [t for t in self.trials if not t.ok]
        if fails:
            lines.extend(["", "## Failures", ""])
            for t in fails:
                lines.append(
                    f"- **{t.harness}/{t.provider_mode}/{t.prompt_id}**: `{t.error[:200]}`"
                )

        lines.extend(
            [
                "",
                "## Notes",
                "",
                "- **auto**: harness-native auto id (`model-router/auto`, `auto`, `openai/auto`).",
                "- **openai / anthropic / open**: passthrough to a representative model in that family.",
                "- Dry-run does not call providers; latency is gateway-only; costs are policy estimates.",
                "- Live mode needs `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `FIREWORKS_API_KEY` in gateway `.env`.",
                "",
            ]
        )
        return "\n".join(lines) + "\n"


def _http_json(
    method: str, path: str, payload: dict | None = None, headers: dict | None = None
) -> tuple[dict, float]:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read().decode())
    return body, (time.perf_counter() - t0) * 1000.0


def _resolve_model(harness: str, provider_mode: str) -> tuple[str, str]:
    if provider_mode == "auto":
        return HARNESSES[harness]["auto_model"], "router"
    meta = PROVIDER_MODES[provider_mode]
    return meta["model"], meta["family"]


def run_trial(
    *,
    harness: str,
    provider_mode: str,
    prompt: dict[str, Any],
    dry_run: bool,
) -> Trial:
    requested, family = _resolve_model(harness, provider_mode)
    hcfg = HARNESSES[harness]
    tools = prompt["tools"]
    if prompt["id"] == "agent" and hcfg["use_tools_on_agent"] and tools is None:
        tools = PROMPTS[2]["tools"]
    # Holmes always attaches tools on agent; other harnesses may omit
    if harness != "holmesgpt" and prompt["id"] != "agent":
        tools = None
    if harness == "holmesgpt" and prompt["id"] == "agent":
        tools = prompt["tools"]
    elif harness == "holmesgpt" and prompt["id"] != "agent":
        # Still OK without tools for chat/code
        tools = None

    headers = {
        "X-Session-Id": f"{hcfg['session']}-{provider_mode}-{prompt['id']}",
        "X-Harness": harness,
        **hcfg["headers_extra"],
    }

    try:
        # Always explain first for task + selection metadata
        explain_body: dict[str, Any] = {
            "model": requested,
            "messages": [{"role": "user", "content": prompt["content"]}],
        }
        if tools:
            explain_body["tools"] = tools
        explain, explain_ms = _http_json("POST", "/v1/router/explain", explain_body, headers)
        decision = explain.get("decision") or {}
        classification = explain.get("classification") or {}
        selected = decision.get("selected_model") or (
            None if provider_mode == "auto" else requested
        )
        litellm_model = (
            decision.get("litellm_model")
            or explain.get("litellm_model")
            or (None if provider_mode == "auto" else requested)
        )
        est = decision.get("estimated_cost_usd")
        task = classification.get("task_type")

        # Chat path (dry gateway returns synthetic content; live calls providers)
        chat_model = requested if provider_mode == "auto" else requested
        chat_body: dict[str, Any] = {
            "model": chat_model,
            "temperature": 0,
            "max_tokens": 64 if prompt["id"] == "chat" else 256,
            "messages": [{"role": "user", "content": prompt["content"]}],
        }
        if tools:
            chat_body["tools"] = tools
        chat, chat_ms = _http_json("POST", "/v1/chat/completions", chat_body, headers)
        msg = ((chat.get("choices") or [{}])[0].get("message") or {})
        content = str(msg.get("content") or "")
        if not content and msg.get("tool_calls"):
            content = f"[tool_calls:{len(msg['tool_calls'])}]"
        mr = chat.get("model_router") or {}
        chat_decision = mr.get("decision") or {}
        if chat_decision.get("selected_model"):
            selected = chat_decision.get("selected_model")
            litellm_model = chat_decision.get("litellm_model") or litellm_model
            est = chat_decision.get("estimated_cost_usd", est)
        actual = None
        # usage cost not always present
        latency = explain_ms + chat_ms
        ok = bool(content) or bool(msg.get("tool_calls"))
        if dry_run and not ok:
            ok = selected is not None
        return Trial(
            harness=harness,
            provider_mode=provider_mode,
            prompt_id=prompt["id"],
            requested_model=requested,
            ok=ok,
            latency_ms=latency,
            selected_model=selected,
            litellm_model=litellm_model,
            task_type=task,
            estimated_cost_usd=float(est) if est is not None else None,
            actual_cost_usd=actual,
            content_preview=content[:120].replace("\n", " "),
            family=family,
        )
    except urllib.error.HTTPError as exc:
        err = exc.read().decode()[:400]
        return Trial(
            harness=harness,
            provider_mode=provider_mode,
            prompt_id=prompt["id"],
            requested_model=requested,
            ok=False,
            latency_ms=0.0,
            error=f"HTTP {exc.code}: {err}",
            family=family,
        )
    except Exception as exc:  # noqa: BLE001
        return Trial(
            harness=harness,
            provider_mode=provider_mode,
            prompt_id=prompt["id"],
            requested_model=requested,
            ok=False,
            latency_ms=0.0,
            error=str(exc),
            family=family,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Prefer dry gateway semantics")
    parser.add_argument("--live", action="store_true", help="Expect live provider calls")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=ROOT / "logs" / "harness_provider_bench.md",
    )
    parser.add_argument(
        "--harnesses",
        default="opencode,hermes,holmesgpt",
        help="Comma-separated harness ids",
    )
    parser.add_argument(
        "--providers",
        default="auto,openai,anthropic,open",
        help="Comma-separated provider modes",
    )
    args = parser.parse_args()
    dry = args.dry_run or not args.live

    try:
        health, _ = _http_json("GET", "/health")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: gateway not reachable at {BASE}: {exc}", file=sys.stderr)
        return 1
    print("health:", health)

    harnesses = [h.strip() for h in args.harnesses.split(",") if h.strip()]
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    report = Report(
        generated_at=datetime.now(timezone.utc).isoformat(),
        base=BASE,
        dry_run=dry,
    )

    for harness in harnesses:
        if harness not in HARNESSES:
            print(f"skip unknown harness {harness}", file=sys.stderr)
            continue
        for mode in providers:
            if mode not in PROVIDER_MODES:
                print(f"skip unknown provider {mode}", file=sys.stderr)
                continue
            for prompt in PROMPTS:
                # Holmes agent prompt must include tools
                p = dict(prompt)
                if harness == "holmesgpt" and prompt["id"] == "agent":
                    p["tools"] = prompt["tools"]
                print(f"→ {harness}/{mode}/{prompt['id']} ...", flush=True)
                trial = run_trial(
                    harness=harness, provider_mode=mode, prompt=p, dry_run=dry
                )
                report.trials.append(trial)
                status = "OK" if trial.ok else "FAIL"
                print(
                    f"  {status} selected={trial.selected_model} "
                    f"task={trial.task_type} {trial.latency_ms:.0f}ms"
                )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    md = report.to_markdown()
    args.output.write_text(md, encoding="utf-8")
    json_path = args.output.with_suffix(".json")
    json_path.write_text(
        json.dumps(
            {
                "generated_at": report.generated_at,
                "base": report.base,
                "dry_run": report.dry_run,
                "trials": [asdict(t) for t in report.trials],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote {args.output}")
    print(f"Wrote {json_path}")
    print(md)
    return 0 if all(t.ok for t in report.trials) else 2


if __name__ == "__main__":
    raise SystemExit(main())
