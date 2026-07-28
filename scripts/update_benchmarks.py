#!/usr/bin/env python3
"""Best-effort refresh of config/benchmarks.yaml from public leaderboards.

No provider API keys required. Partial updates are OK: unavailable sources are
skipped with clear logs; snapshot_date is still bumped when the run succeeds.

Usage:
  python scripts/update_benchmarks.py
  python scripts/update_benchmarks.py --dry-run
  python scripts/update_benchmarks.py --summary logs/benchmark_update_summary.md
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ERROR: PyYAML is required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARKS = ROOT / "config" / "benchmarks.yaml"
USER_AGENT = "prism-router-benchmark-updater/0.1 (+https://github.com/pavneeta/prism-router)"
HTTP_TIMEOUT_S = 45

# Catalog model id → DeepSWE leaderboard model slug(s), preferred first.
DEEPSWE_ALIASES: dict[str, list[str]] = {
    "openai/gpt-5.6-sol": ["gpt-5-6-sol", "gpt-5.6-sol"],
    "openai/gpt-5.6-terra": ["gpt-5-6-terra", "gpt-5.6-terra"],
    "openai/gpt-5.6-luna": ["gpt-5-6-luna", "gpt-5.6-luna"],
    "anthropic/claude-opus-5": ["claude-opus-5"],
    "anthropic/claude-sonnet-5": ["claude-sonnet-5"],
    "moonshot/kimi-k3": ["kimi-k3"],
    "zai/glm-5.2": ["glm-5-2", "glm-5.2"],
}

DEEPSWE_URLS = [
    "https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json",
    "https://deepswe.datacurve.ai/artifacts/leaderboard-live.json",
]

# Prefer max-effort rows when multiple configs exist for one model.
_EFFORT_RANK = {"max": 5, "xhigh": 4, "high": 3, "medium": 2, "default": 1, "low": 0}

logger = logging.getLogger("update_benchmarks")


@dataclass
class SourceResult:
    name: str
    ok: bool
    message: str
    scores: dict[str, float] = field(default_factory=dict)  # catalog_id → value
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Change:
    model_id: str
    source_key: str
    old: Any
    new: Any


def _http_get_json(url: str) -> Any:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
        raw = resp.read()
        ctype = (resp.headers.get("Content-Type") or "").lower()
    text = raw.decode("utf-8", errors="replace")
    if "html" in ctype or text.lstrip().startswith("<!"):
        raise ValueError(f"expected JSON from {url}, got HTML/non-JSON")
    return json.loads(text)


def _round_rate(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def _discover_deepswe_urls() -> list[str]:
    """Best-effort: scrape DeepSWE homepage for artifact paths."""
    urls = list(DEEPSWE_URLS)
    try:
        req = Request(
            "https://deepswe.datacurve.ai/",
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        with urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        for path in re.findall(r"/artifacts/[^\"'\s]+leaderboard-live\.json", html):
            full = "https://deepswe.datacurve.ai" + path
            if full not in urls:
                urls.insert(0, full)
    except Exception as exc:  # noqa: BLE001 — discovery is optional
        logger.info("DeepSWE URL discovery skipped: %s", exc)
    return urls


def fetch_deepswe() -> SourceResult:
    """Fetch DeepSWE pass@1 (prefer mini-swe-agent + max effort)."""
    last_err = "no URL attempted"
    data: dict[str, Any] | None = None
    used_url = ""
    for url in _discover_deepswe_urls():
        try:
            payload = _http_get_json(url)
            if not isinstance(payload, dict) or "rows" not in payload:
                raise ValueError("unexpected payload shape (missing rows)")
            data = payload
            used_url = url
            break
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last_err = f"{url}: {exc}"
            logger.warning("DeepSWE fetch failed: %s", last_err)

    if data is None:
        return SourceResult("deepswe", False, f"unavailable ({last_err})")

    rows = [r for r in data.get("rows") or [] if isinstance(r, dict)]
    # Prefer official mini-swe-agent harness when present.
    mini = [
        r
        for r in rows
        if "mini-swe-agent" in str(r.get("harness") or "").lower().replace("_", "-")
    ]
    if mini:
        rows = mini

    by_slug: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        slug = str(row.get("model") or "").strip()
        if not slug:
            continue
        by_slug.setdefault(slug, []).append(row)

    scores: dict[str, float] = {}
    for catalog_id, aliases in DEEPSWE_ALIASES.items():
        chosen: dict[str, Any] | None = None
        chosen_slug = ""
        for alias in aliases:
            candidates = by_slug.get(alias) or []
            if not candidates:
                continue

            def sort_key(r: dict[str, Any]) -> tuple[int, float]:
                effort = str(r.get("reasoning_effort") or "").lower()
                rate = float(r.get("pass_at_1") if r.get("pass_at_1") is not None else r.get("pass_rate") or 0.0)
                return (_EFFORT_RANK.get(effort, -1), rate)

            candidates = sorted(candidates, key=sort_key, reverse=True)
            chosen = candidates[0]
            chosen_slug = alias
            break
        if chosen is None:
            continue
        rate = chosen.get("pass_at_1")
        if rate is None:
            rate = chosen.get("pass_rate")
        if rate is None:
            continue
        scores[catalog_id] = _round_rate(float(rate))
        logger.info(
            "DeepSWE %s ← %s (%s) = %.3f",
            catalog_id,
            chosen_slug,
            chosen.get("reasoning_effort") or chosen.get("config"),
            scores[catalog_id],
        )

    generated = str(data.get("generated_at") or "")
    return SourceResult(
        name="deepswe",
        ok=bool(scores),
        message=f"ok from {used_url}" + (f" generated_at={generated}" if generated else ""),
        scores=scores,
        meta={"url": used_url, "generated_at": generated, "n_rows": len(rows)},
    )


def fetch_aa_intelligence_index() -> SourceResult:
    """Best-effort AA-like composites from public endpoints (skip if auth required)."""
    urls = [
        "https://artificialanalysis.ai/api/models",
        "https://artificialanalysis.ai/data/llms.json",
        "https://cdn.artificialanalysis.ai/data/llms.json",
    ]
    for url in urls:
        try:
            payload = _http_get_json(url)
            scores = _parse_aa_payload(payload)
            if scores:
                return SourceResult(
                    "aa_intelligence_index",
                    True,
                    f"parsed {len(scores)} scores from {url}",
                    scores=scores,
                )
        except Exception as exc:  # noqa: BLE001
            logger.info("AA fetch failed (%s): %s", url, exc)
    return SourceResult(
        "aa_intelligence_index",
        False,
        "skip: Artificial Analysis API requires a key or public mirror unavailable",
    )


def _parse_aa_payload(payload: Any) -> dict[str, float]:
    aliases = {
        "claude-opus-5": "anthropic/claude-opus-5",
        "claude opus 5": "anthropic/claude-opus-5",
        "claude-sonnet-5": "anthropic/claude-sonnet-5",
        "gpt-5.6-sol": "openai/gpt-5.6-sol",
        "gpt-5.6 sol": "openai/gpt-5.6-sol",
        "kimi-k3": "moonshot/kimi-k3",
        "kimi k3": "moonshot/kimi-k3",
        "glm-5.2": "zai/glm-5.2",
        "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
        "deepseek v4 pro": "deepseek/deepseek-v4-pro",
    }
    if isinstance(payload, dict):
        rows = payload.get("models") or payload.get("data") or payload.get("results") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        return {}
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("slug") or row.get("model") or "").lower()
        idx = row.get("intelligence_index") or row.get("aa_intelligence_index") or row.get("index")
        if idx is None:
            continue
        for key, catalog_id in aliases.items():
            if key in name:
                out[catalog_id] = float(idx)
                break
    return out


def fetch_arena_elo() -> SourceResult:
    """Fetch Arena text Elo from public community JSON / HF datasets (no auth)."""
    urls = [
        "https://api.wulong.dev/arena-ai-leaderboards/v1/leaderboard?name=text",
        "https://raw.githubusercontent.com/oolong-tea-2026/arena-ai-leaderboards/main/data/latest.json",
        # Hugging Face datasets-server rows for lmarena text leaderboard
        "https://datasets-server.huggingface.co/rows?dataset=lmarena-ai/leaderboard-dataset&config=text&split=latest&offset=0&length=100",
    ]
    last_err = "no URL"
    for url in urls:
        try:
            payload = _http_get_json(url)
            if isinstance(payload, dict) and "models" not in payload:
                text_url = payload.get("text") or (payload.get("paths") or {}).get("text")
                if isinstance(text_url, str) and text_url.startswith("http"):
                    payload = _http_get_json(text_url)
                elif isinstance(text_url, str):
                    base = "https://raw.githubusercontent.com/oolong-tea-2026/arena-ai-leaderboards/main/"
                    payload = _http_get_json(base + text_url.lstrip("/"))
            scores = _parse_arena_payload(payload)
            if scores:
                return SourceResult(
                    "arena_elo",
                    True,
                    f"parsed {len(scores)} Elo scores from {url}",
                    scores=scores,
                )
            last_err = f"no mapped models in payload from {url}"
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            logger.info("Arena fetch failed (%s): %s", url, exc)
    return SourceResult("arena_elo", False, f"skip: {last_err}")


def _parse_arena_payload(payload: Any) -> dict[str, float]:
    aliases = {
        "claude-opus-5": "anthropic/claude-opus-5",
        "claude opus 5": "anthropic/claude-opus-5",
        "claude-sonnet-5": "anthropic/claude-sonnet-5",
        "claude sonnet 5": "anthropic/claude-sonnet-5",
        "gpt-5.6-sol": "openai/gpt-5.6-sol",
        "gpt-5.6 sol": "openai/gpt-5.6-sol",
        "gpt-4o-mini": "openai/gpt-4o-mini",
        "gpt-4o": "openai/gpt-4o",
        "kimi-k3": "moonshot/kimi-k3",
        "kimi k3": "moonshot/kimi-k3",
        "glm-5.2": "zai/glm-5.2",
        "deepseek": "deepseek/deepseek-v4-pro",
    }
    if isinstance(payload, dict):
        # HF datasets-server: {"rows":[{"row":{...}}, ...]}
        if "rows" in payload and isinstance(payload["rows"], list):
            models = []
            for item in payload["rows"]:
                if isinstance(item, dict) and isinstance(item.get("row"), dict):
                    row = item["row"]
                    # Prefer overall category when present
                    cat = str(row.get("category") or "overall").lower()
                    if cat not in ("overall", "text", ""):
                        continue
                    models.append(
                        {
                            "model": row.get("model_name") or row.get("model"),
                            "score": row.get("rating") or row.get("score"),
                        }
                    )
        else:
            models = payload.get("models") or payload.get("data") or []
    elif isinstance(payload, list):
        models = payload
    else:
        return {}
    out: dict[str, float] = {}
    for row in models:
        if not isinstance(row, dict):
            continue
        name = str(row.get("model") or row.get("name") or row.get("model_name") or "").lower()
        score = row.get("score") or row.get("elo") or row.get("rating")
        if score is None:
            continue
        for key, catalog_id in aliases.items():
            if key in name and catalog_id not in out:
                out[catalog_id] = float(score)
                break
    return out


def fetch_swe_bench_verified() -> SourceResult:
    """Best-effort SWE-bench Verified from public JSON mirrors / GitHub experiments."""
    urls = [
        "https://raw.githubusercontent.com/SWE-bench/experiments/main/evaluation/verified/docs/index.json",
        "https://raw.githubusercontent.com/SWE-bench/experiments/main/docs/index.json",
        "https://www.swebench.com/api/verified.json",
        "https://raw.githubusercontent.com/princeton-nlp/SWE-bench/main/docs/results.json",
    ]
    last_err = "no URL"
    for url in urls:
        try:
            payload = _http_get_json(url)
            scores = _parse_swe_payload(payload)
            if scores:
                return SourceResult(
                    "swe_bench_verified",
                    True,
                    f"parsed {len(scores)} scores from {url}",
                    scores=scores,
                )
            last_err = f"unmapped payload from {url}"
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            logger.info("SWE-bench fetch failed (%s): %s", url, exc)

    # Fall back: scan recent verified experiment folders on GitHub for results.json
    try:
        listing = _http_get_json(
            "https://api.github.com/repos/SWE-bench/experiments/contents/evaluation/verified"
        )
        if isinstance(listing, list):
            scores: dict[str, float] = {}
            for entry in listing[-40:]:  # newest-ish tail of alpha-sorted list
                if not isinstance(entry, dict) or entry.get("type") != "dir":
                    continue
                name = str(entry.get("name") or "").lower()
                if not any(
                    k in name
                    for k in ("claude", "gpt", "deepseek", "kimi", "glm", "opus", "sonnet")
                ):
                    continue
                path = entry.get("path")
                if not path:
                    continue
                try:
                    results = _http_get_json(
                        f"https://raw.githubusercontent.com/SWE-bench/experiments/main/{path}/results.json"
                    )
                except Exception:  # noqa: BLE001
                    continue
                parsed = _parse_swe_payload(results if isinstance(results, list) else {"results": [results] if isinstance(results, dict) else results})
                # Also accept resolved_instances / total style
                if not parsed and isinstance(results, dict):
                    resolved = results.get("resolved_instances") or results.get("resolved")
                    total = results.get("total_instances") or results.get("total")
                    if resolved is not None and total:
                        fake = {"model": name, "resolved": float(resolved) / float(total)}
                        parsed = _parse_swe_payload({"results": [fake]})
                    elif isinstance(resolved, (int, float)) and float(resolved) <= 1.0:
                        parsed = _parse_swe_payload(
                            {"results": [{"model": name, "resolved": float(resolved)}]}
                        )
                for mid, val in parsed.items():
                    scores[mid] = max(scores.get(mid, 0.0), val)
            if scores:
                return SourceResult(
                    "swe_bench_verified",
                    True,
                    f"parsed {len(scores)} scores from SWE-bench experiments tree",
                    scores=scores,
                )
            last_err = "no mapped models in SWE-bench experiments tree"
    except Exception as exc:  # noqa: BLE001
        last_err = str(exc)
        logger.info("SWE-bench GitHub scan failed: %s", exc)

    return SourceResult(
        "swe_bench_verified",
        False,
        f"skip: no stable public SWE-bench Verified JSON ({last_err})",
    )


def _parse_swe_payload(payload: Any) -> dict[str, float]:
    aliases = {
        "claude-opus-5": "anthropic/claude-opus-5",
        "claude-opus-4": "anthropic/claude-opus-5",
        "gpt-5.6": "openai/gpt-5.6-sol",
        "gpt-4o": "openai/gpt-4o",
        "deepseek": "deepseek/deepseek-v4-pro",
        "kimi": "moonshot/kimi-k3",
    }
    if isinstance(payload, dict):
        rows = payload.get("results") or payload.get("leaderboard") or payload.get("data") or []
        if not rows and all(isinstance(v, (int, float)) for v in payload.values()):
            rows = [{"model": k, "resolved": v} for k, v in payload.items()]
    elif isinstance(payload, list):
        rows = payload
    else:
        return {}
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("model") or row.get("name") or row.get("system") or "").lower()
        score = row.get("resolved") or row.get("score") or row.get("pass_rate")
        if score is None:
            continue
        val = float(score)
        if val > 1.0:
            val = val / 100.0
        for key, catalog_id in aliases.items():
            if key in name and catalog_id not in out:
                out[catalog_id] = round(val, 3)
                break
    return out


def fetch_terminal_bench() -> SourceResult:
    """Best-effort Terminal-Bench v2.1 from public mirrors / Harbor / tbench API."""
    urls = [
        "https://api.tbench.ai/v1/get_leaderboard?benchmark=terminal-bench&version=2.1",
        "https://api.tbench.ai/v1/get_leaderboard?benchmark=terminal-bench-2&version=2.1",
        "https://raw.githubusercontent.com/laude-institute/terminal-bench/main/leaderboard.json",
        "https://raw.githubusercontent.com/laude-institute/terminal-bench/main/terminal_bench/leaderboard.json",
        "https://www.tbench.ai/api/v2/leaderboard.json",
        "https://www.tbench.ai/leaderboard.json",
        "https://hub.harborframework.com/api/datasets/terminal-bench/terminal-bench-2-1/latest/leaderboard.json",
    ]
    last_err = "no URL"
    for url in urls:
        try:
            payload = _http_get_json(url)
            scores = _parse_terminal_payload(payload)
            if scores:
                return SourceResult(
                    "terminal_bench_v2_1",
                    True,
                    f"parsed {len(scores)} scores from {url}",
                    scores=scores,
                )
            last_err = f"unmapped payload from {url}"
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            logger.info("Terminal-Bench fetch failed (%s): %s", url, exc)
    return SourceResult(
        "terminal_bench_v2_1",
        False,
        f"skip: Terminal-Bench public JSON not available ({last_err})",
    )


def _parse_terminal_payload(payload: Any) -> dict[str, float]:
    aliases = {
        "claude-opus-5": "anthropic/claude-opus-5",
        "claude-sonnet-5": "anthropic/claude-sonnet-5",
        "gpt-5.6-sol": "openai/gpt-5.6-sol",
        "gpt-5.6-terra": "openai/gpt-5.6-terra",
        "gpt-5.6-luna": "openai/gpt-5.6-luna",
        "kimi-k3": "moonshot/kimi-k3",
        "glm-5.2": "zai/glm-5.2",
        "glm-5p2": "zai/glm-5.2",
        "deepseek": "deepseek/deepseek-v4-pro",
        "minimax": "minimax/minimax-m3",
    }
    if isinstance(payload, dict):
        rows = payload.get("results") or payload.get("models") or payload.get("leaderboard") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        return {}
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("model") or row.get("name") or "").lower()
        score = row.get("score") or row.get("pass_at_1") or row.get("accuracy")
        if score is None:
            continue
        val = float(score)
        if val > 1.0:
            val = val / 100.0
        for key, catalog_id in aliases.items():
            if key in name and catalog_id not in out:
                out[catalog_id] = round(val, 3)
                break
    return out


def _format_source_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value.is_integer() and abs(value) >= 1:
            return str(int(value))
        return f"{value:.3f}"
    return str(value)


def update_source_value(text: str, model_id: str, source_key: str, new_value: Any) -> tuple[str, bool]:
    """Update a source field under a model; return (new_text, changed)."""
    model_pat = re.compile(
        rf"(^[ \t]*)({re.escape(model_id)}:)[ \t]*\n",
        re.MULTILINE,
    )
    m = model_pat.search(text)
    if not m:
        logger.warning("model %s not found in YAML; skip %s", model_id, source_key)
        return text, False
    start = m.end()
    next_model = re.search(r"\n  [^\s#].*:\s*(?:#.*)?\n", text[start:])
    end = start + next_model.start() + 1 if next_model else len(text)
    block = text[start:end]

    new_raw = _format_source_value(new_value)
    src_pat = re.compile(
        rf"^([ \t]*)({re.escape(source_key)}:)[ \t]*([^\n#]*?)([ \t]*(?:#.*)?)?$",
        re.MULTILINE,
    )
    sm = src_pat.search(block)
    if not sm:
        logger.warning("source %s missing under %s; skip", source_key, model_id)
        return text, False

    old_raw = sm.group(3).strip()
    if old_raw == new_raw:
        return text, False

    indent, key, comment = sm.group(1), sm.group(2), sm.group(4) or ""
    replacement = f"{indent}{key} {new_raw}{comment}"
    new_block = block[: sm.start()] + replacement + block[sm.end() :]
    return text[:start] + new_block + text[end:], True


def update_snapshot_date(text: str, snapshot: str) -> tuple[str, bool]:
    pat = re.compile(r'^(snapshot_date:\s*)(["\']?)([^"\'\n]+)(["\']?)(\s*(?:#.*)?)?$', re.MULTILINE)
    m = pat.search(text)
    if not m:
        logger.warning("snapshot_date field missing")
        return text, False
    if m.group(3) == snapshot:
        return text, False
    # Prefer quoted ISO date to match seed style
    replacement = f'{m.group(1)}"{snapshot}"{m.group(5) or ""}'
    return text[: m.start()] + replacement + text[m.end() :], True


def apply_updates(
    text: str,
    results: list[SourceResult],
    snapshot: str,
) -> tuple[str, list[Change], list[str]]:
    """Merge successful source scores into YAML text."""
    data = yaml.safe_load(text) or {}
    models: dict[str, Any] = (data.get("models") or {}) if isinstance(data, dict) else {}
    changes: list[Change] = []
    notes: list[str] = []

    for result in results:
        if not result.ok:
            notes.append(f"- **{result.name}**: skipped — {result.message}")
            continue
        notes.append(f"- **{result.name}**: {result.message} ({len(result.scores)} model scores)")
        for model_id, new_val in sorted(result.scores.items()):
            entry = models.get(model_id) or {}
            sources = (entry.get("sources") or {}) if isinstance(entry, dict) else {}
            old_val = sources.get(result.name)
            if model_id not in models:
                notes.append(f"  - {model_id}: not in catalog; skip")
                continue
            if result.name not in sources:
                notes.append(f"  - {model_id}: no existing `{result.name}` key; skip")
                continue
            text, changed = update_source_value(text, model_id, result.name, new_val)
            if changed:
                changes.append(Change(model_id, result.name, old_val, new_val))
            else:
                notes.append(
                    f"  - {model_id}.{result.name}: unchanged ({_format_source_value(new_val)})"
                )

    prev_snap = data.get("snapshot_date") if isinstance(data, dict) else None
    text, snap_changed = update_snapshot_date(text, snapshot)
    if snap_changed:
        changes.append(Change("_meta", "snapshot_date", prev_snap, snapshot))
        notes.append(f"- **snapshot_date**: `{prev_snap}` → `{snapshot}`")
    else:
        notes.append(f"- **snapshot_date**: already `{snapshot}`")

    return text, changes, notes


def build_summary(
    results: list[SourceResult],
    changes: list[Change],
    notes: list[str],
    snapshot: str,
    dry_run: bool,
) -> str:
    lines = [
        f"# Benchmark update summary ({snapshot})",
        "",
        f"- Mode: `{'dry-run' if dry_run else 'write'}`",
        f"- Generated (UTC): `{datetime.now(timezone.utc).isoformat()}`",
        "",
        "## Sources",
        "",
        *notes,
        "",
        "## Score changes",
        "",
    ]
    score_changes = [c for c in changes if c.model_id != "_meta"]
    if not score_changes:
        lines.append("_No per-model source values changed._")
    else:
        for c in score_changes:
            lines.append(f"- `{c.model_id}` `{c.source_key}`: {c.old} → {c.new}")
    lines.append("")
    ok_count = sum(1 for r in results if r.ok)
    lines.append(f"Fetched successfully: **{ok_count}/{len(results)}** sources.")
    lines.append("")
    return "\n".join(lines) + "\n"


def run(
    benchmarks_path: Path,
    *,
    dry_run: bool,
    summary_path: Path | None,
) -> int:
    if not benchmarks_path.is_file():
        logger.error("benchmarks file not found: %s", benchmarks_path)
        return 1

    original = benchmarks_path.read_text(encoding="utf-8")
    snapshot = date.today().isoformat()

    results = [
        fetch_deepswe(),
        fetch_swe_bench_verified(),
        fetch_terminal_bench(),
        fetch_aa_intelligence_index(),
        fetch_arena_elo(),
    ]

    updated, changes, notes = apply_updates(original, results, snapshot)
    summary = build_summary(results, changes, notes, snapshot, dry_run)
    print(summary, end="")

    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(summary, encoding="utf-8")
        logger.info("wrote summary %s", summary_path)

    if updated == original:
        logger.info("no file changes")
        return 0

    if dry_run:
        logger.info("dry-run: would write %d change(s) to %s", len(changes), benchmarks_path)
        return 0

    benchmarks_path.write_text(updated, encoding="utf-8")
    logger.info("wrote %s (%d change(s))", benchmarks_path, len(changes))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmarks",
        type=Path,
        default=DEFAULT_BENCHMARKS,
        help="Path to benchmarks.yaml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and report changes without writing benchmarks.yaml",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="Optional path for markdown summary (e.g. logs/benchmark_update_summary.md)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    return run(args.benchmarks, dry_run=args.dry_run, summary_path=args.summary)


if __name__ == "__main__":
    raise SystemExit(main())
