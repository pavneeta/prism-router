#!/usr/bin/env python3
"""50-scenario stress bench across OpenAI / Anthropic / OSS (+ Prism auto).

Dry-run:
  MODEL_ROUTER_DRY_RUN=true model-router
  python scripts/stress_bench.py --dry-run --limit 50

Live (skips missing provider keys):
  MODEL_ROUTER_DRY_RUN=false model-router
  python scripts/stress_bench.py --live --token-budget 2800000
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
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from model_router.stress.scoring import score_response  # noqa: E402

BASE = os.environ.get("PRISM_BASE", "http://127.0.0.1:4000")
SCENARIOS = ROOT / "benchmarks" / "scenarios" / "v1" / "scenarios.jsonl"

# Representative panel
DEFAULT_MODELS = [
    "auto",
    "openai/gpt-4o-mini",
    "openai/gpt-5.6-luna",
    "anthropic/claude-sonnet-5",
    "deepseek/deepseek-v4-pro",
    "moonshot/kimi-k3",
    "zai/glm-5.2",
]

FAMILY = {
    "auto": "router",
    "openai/gpt-4o-mini": "openai",
    "openai/gpt-5.6-luna": "openai",
    "openai/gpt-5.6-sol": "openai",
    "anthropic/claude-sonnet-5": "anthropic",
    "anthropic/claude-opus-5": "anthropic",
    "deepseek/deepseek-v4-pro": "open",
    "moonshot/kimi-k3": "open",
    "zai/glm-5.2": "open",
}

HARD_CODING = {
    "cg_05_lru_get",
    "cg_08_debounce_note",
    "tu_03_multi_tool",
    "cr_05_async_await",
}


@dataclass
class Result:
    scenario_id: str
    task_type: str
    model: str
    family: str
    ok: bool
    score: float
    pass_: bool
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None
    selected_model: str | None = None
    classified_task: str | None = None
    classify_ok: bool | None = None
    detail: str = ""
    error: str = ""


@dataclass
class RunState:
    run_id: str
    dry_run: bool
    token_budget: int
    tokens_used: int = 0
    results: list[Result] = field(default_factory=list)
    skipped_models: list[str] = field(default_factory=list)


def _http(method: str, path: str, payload: dict | None = None, headers: dict | None = None) -> tuple[dict, float]:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = json.loads(resp.read().decode())
    return body, (time.perf_counter() - t0) * 1000.0


def load_scenarios(path: Path, limit: int | None = None, tasks: set[str] | None = None) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if tasks and row["task_type"] not in tasks:
                continue
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    return rows


def detect_available_families() -> set[str]:
    """Probe health; family availability inferred from env if present on runner.

    Gateway holds keys; we probe with a tiny dry explain and optional live ping
    via env flags on this process for documentation. Prefer GATEWAY probe:
    attempt a 1-token completion only when --live.
    """
    families = {"router"}  # auto always attempted
    # Env mirrors what operator put in gateway .env (best-effort)
    if os.environ.get("OPENAI_API_KEY"):
        families.add("openai")
    if os.environ.get("ANTHROPIC_API_KEY"):
        families.add("anthropic")
    if os.environ.get("FIREWORKS_API_KEY"):
        families.add("open")
    return families


def resolve_models(models: list[str], live: bool, force_all: bool) -> tuple[list[str], list[str]]:
    if not live or force_all:
        return models, []
    fams = detect_available_families()
    keep, skip = [], []
    for m in models:
        fam = FAMILY.get(m, "unknown")
        if fam == "router" or fam in fams:
            keep.append(m)
        else:
            skip.append(m)
    # If no keys at all in runner env, still try all in live mode but expect failures —
    # prefer skipping OSS/OA/ANTH when env empty to save time; user may only set gateway .env
    if fams == {"router"} and live:
        # Try all models; gateway may still have keys even if this shell doesn't.
        return models, []
    return keep, skip


def run_one(scenario: dict, model: str, dry_run: bool) -> Result:
    sid = scenario["id"]
    task = scenario["task_type"]
    headers = {
        "X-Session-Id": f"stress-{sid}-{model.replace('/', '_')}",
        "X-Harness": "stress-bench",
    }
    req_model = "model-router/auto" if model == "auto" else model
    body: dict[str, Any] = {
        "model": req_model,
        "temperature": 0,
        "max_tokens": int(scenario.get("max_tokens") or 512),
        "messages": scenario["messages"],
    }
    if scenario.get("tools"):
        body["tools"] = scenario["tools"]
        body["tool_choice"] = "auto"

    # Opus boost on hardest coding only (optional passthrough if listed)
    if model == "anthropic/claude-sonnet-5" and sid in HARD_CODING and os.environ.get(
        "STRESS_USE_OPUS_HARD"
    ):
        body["model"] = "anthropic/claude-opus-5"

    try:
        explain, _ = _http(
            "POST",
            "/v1/router/explain",
            {
                "model": req_model,
                "messages": scenario["messages"],
                **({"tools": scenario["tools"]} if scenario.get("tools") else {}),
            },
            headers,
        )
        classified = (explain.get("classification") or {}).get("task_type")
        decision = explain.get("decision") or {}
        selected = decision.get("selected_model") or (None if model == "auto" else model)
        est = decision.get("estimated_cost_usd")
        classify_ok = classified == scenario.get("expect_task")

        chat, latency = _http("POST", "/v1/chat/completions", body, headers)
        choice = (chat.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = str(message.get("content") or "")
        usage = chat.get("usage") or {}
        pt = int(usage.get("prompt_tokens") or 0)
        ct = int(usage.get("completion_tokens") or 0)
        # dry-run often returns 0 usage — estimate from lengths
        if dry_run and pt == 0:
            prompt_txt = "\n".join(str(m.get("content") or "") for m in scenario["messages"])
            pt = max(1, len(prompt_txt) // 4)
            ct = max(1, len(content) // 4)

        mr = chat.get("model_router") or {}
        if (mr.get("decision") or {}).get("selected_model"):
            selected = mr["decision"]["selected_model"]
            est = mr["decision"].get("estimated_cost_usd", est)

        scored = score_response(checks=scenario.get("checks"), content=content, message=message)
        # In dry-run, python_exec / tool_call will often fail — treat classify+HTTP as soft pass for wiring
        if dry_run and not scored["pass"]:
            soft = selected is not None or model != "auto"
            return Result(
                scenario_id=sid,
                task_type=task,
                model=model,
                family=FAMILY.get(model, "unknown"),
                ok=True,
                score=0.0,
                pass_=False,
                latency_ms=latency,
                prompt_tokens=pt,
                completion_tokens=ct,
                total_tokens=pt + ct,
                estimated_cost_usd=float(est) if est is not None else None,
                selected_model=selected,
                classified_task=classified,
                classify_ok=classify_ok,
                detail=f"dry_soft:{scored['detail']}",
            )

        return Result(
            scenario_id=sid,
            task_type=task,
            model=model,
            family=FAMILY.get(model, "unknown"),
            ok=True,
            score=float(scored["score"]),
            pass_=bool(scored["pass"]),
            latency_ms=latency,
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=pt + ct,
            estimated_cost_usd=float(est) if est is not None else None,
            selected_model=selected,
            classified_task=classified,
            classify_ok=classify_ok,
            detail=str(scored.get("detail") or ""),
        )
    except urllib.error.HTTPError as exc:
        err = exc.read().decode()[:500]
        return Result(
            scenario_id=sid,
            task_type=task,
            model=model,
            family=FAMILY.get(model, "unknown"),
            ok=False,
            score=0.0,
            pass_=False,
            latency_ms=0.0,
            error=f"HTTP {exc.code}: {err}",
        )
    except Exception as exc:  # noqa: BLE001
        return Result(
            scenario_id=sid,
            task_type=task,
            model=model,
            family=FAMILY.get(model, "unknown"),
            ok=False,
            score=0.0,
            pass_=False,
            latency_ms=0.0,
            error=str(exc),
        )


def write_report(state: RunState, out_dir: Path) -> Path:
    results = state.results
    by_tm: dict[tuple[str, str], list[Result]] = defaultdict(list)
    for r in results:
        by_tm[(r.task_type, r.model)].append(r)

    lines = [
        f"# Stress bench report `{state.run_id}`",
        "",
        f"- Mode: `{'dry-run' if state.dry_run else 'live'}`",
        f"- Tokens used (sum usage): **{state.tokens_used}** / budget {state.token_budget}",
        f"- Trials: {len(results)} · HTTP OK: {sum(1 for r in results if r.ok)} · "
        f"Quality pass: {sum(1 for r in results if r.pass_)}",
        f"- Skipped models: {', '.join(state.skipped_models) or '—'}",
        "",
        "## Pass rate by task × model",
        "",
        "| Task | Model | n | pass% | mean score | mean est $ |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for (task, model), rs in sorted(by_tm.items()):
        n = len(rs)
        p = 100.0 * sum(1 for r in rs if r.pass_) / n if n else 0
        ms = statistics.mean(r.score for r in rs)
        costs = [r.estimated_cost_usd for r in rs if r.estimated_cost_usd is not None]
        cost_s = f"{statistics.mean(costs):.6f}" if costs else "—"
        lines.append(f"| {task} | `{model}` | {n} | {p:.0f}% | {ms:.2f} | {cost_s} |")

    # Classifier accuracy
    cls = [r for r in results if r.classify_ok is not None]
    if cls:
        acc = 100.0 * sum(1 for r in cls if r.classify_ok) / len(cls)
        lines.extend(["", f"## Classifier accuracy vs expect_task: **{acc:.1f}%**", ""])

    # Auto regret / savings vs best open model
    lines.extend(["## Auto vs families (product hints)", ""])
    by_sid: dict[str, list[Result]] = defaultdict(list)
    for r in results:
        by_sid[r.scenario_id].append(r)
    hints = []
    for sid, rs in by_sid.items():
        auto = next((r for r in rs if r.model == "auto"), None)
        if not auto:
            continue
        opens = [r for r in rs if r.family == "open" and r.pass_]
        frontier = [r for r in rs if r.family in {"openai", "anthropic"} and r.pass_]
        if opens and auto.pass_:
            cheapest_open = min(
                (r.estimated_cost_usd or 1e9 for r in opens),
            )
            if auto.estimated_cost_usd and auto.estimated_cost_usd > 2 * cheapest_open:
                hints.append(f"- `{sid}`: auto est ${auto.estimated_cost_usd:.4f} >> open pass; check floors")
        if frontier and not auto.pass_ and not opens:
            hints.append(f"- `{sid}`: auto failed and open failed — floor or capability gap")
        if auto.classify_ok is False:
            hints.append(
                f"- `{sid}`: misclassified as `{auto.classified_task}` "
                f"(expected `{next(r.task_type for r in rs)}`)"
            )
    lines.extend(hints or ["- No strong floor hints from this run (see raw metrics)."])

    # Floor proposal heuristic
    lines.extend(["", "## Suggested floor review", ""])
    task_open_pass: dict[str, list[float]] = defaultdict(list)
    for r in results:
        if r.family == "open":
            task_open_pass[r.task_type].append(1.0 if r.pass_ else 0.0)
    for task, vals in sorted(task_open_pass.items()):
        rate = statistics.mean(vals) if vals else 0
        if rate >= 0.7:
            lines.append(f"- `{task}`: OSS pass≈{rate:.0%} → consider **lowering** floor slightly if auto over-selects frontier")
        elif rate <= 0.3:
            lines.append(f"- `{task}`: OSS pass≈{rate:.0%} → consider **raising** floor or disabling weak OSS for this task")
        else:
            lines.append(f"- `{task}`: OSS pass≈{rate:.0%} → keep floor; gather more live samples")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Dry-run quality pass rates are not meaningful for code/tool checks.",
            "- Live burn requires provider keys on the **gateway** `.env`.",
            "- Raw trials: `results.jsonl` in this directory.",
            "",
        ]
    )
    md_path = out_dir / "report.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--token-budget", type=int, default=2_800_000)
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--tasks", default="")
    ap.add_argument("--force-all-models", action="store_true")
    ap.add_argument("--scenarios", type=Path, default=SCENARIOS)
    args = ap.parse_args()
    dry = args.dry_run or not args.live

    try:
        health, _ = _http("GET", "/health")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: gateway not at {BASE}: {exc}", file=sys.stderr)
        return 1
    print("health:", health)

    if not args.scenarios.exists():
        print("Generating scenarios pack...", flush=True)
        from subprocess import check_call

        check_call([sys.executable, str(ROOT / "scripts" / "generate_stress_scenarios.py")])

    tasks = {t.strip() for t in args.tasks.split(",") if t.strip()} or None
    scenarios = load_scenarios(args.scenarios, limit=args.limit, tasks=tasks)
    models_all = [m.strip() for m in args.models.split(",") if m.strip()]
    models, skipped = resolve_models(models_all, live=not dry, force_all=args.force_all_models)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "logs" / "stress_bench" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    state = RunState(run_id=run_id, dry_run=dry, token_budget=args.token_budget, skipped_models=skipped)

    print(f"scenarios={len(scenarios)} models={models} skipped={skipped} dry={dry}")
    raw_path = out_dir / "results.jsonl"

    with raw_path.open("w", encoding="utf-8") as raw:
        for sc in scenarios:
            for model in models:
                if state.tokens_used >= args.token_budget:
                    print("Token budget reached; stopping.")
                    break
                print(f"→ {sc['id']} × {model}", flush=True)
                result = run_one(sc, model, dry_run=dry)
                state.results.append(result)
                state.tokens_used += result.total_tokens
                raw.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
                status = "PASS" if result.pass_ else ("OK" if result.ok else "FAIL")
                print(
                    f"  {status} score={result.score:.2f} tok={result.total_tokens} "
                    f"cls={result.classified_task} sel={result.selected_model} {result.detail or result.error}"
                )
            else:
                continue
            break

    metrics = {
        "run_id": run_id,
        "dry_run": dry,
        "tokens_used": state.tokens_used,
        "token_budget": args.token_budget,
        "n_results": len(state.results),
        "n_pass": sum(1 for r in state.results if r.pass_),
        "n_ok": sum(1 for r in state.results if r.ok),
        "skipped_models": skipped,
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    report = write_report(state, out_dir)
    # Copy anonymized aggregate into docs if live and substantial
    if not dry and state.tokens_used > 10_000:
        docs_dir = ROOT / "docs" / "internal" / "stress_runs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        summary = docs_dir / f"{run_id}_summary.md"
        summary.write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Wrote docs summary {summary}")

    print(f"\nReport: {report}")
    print(f"Metrics: {out_dir / 'metrics.json'}")
    print(f"Tokens used: {state.tokens_used}")
    return 0 if all(r.ok for r in state.results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
