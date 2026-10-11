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
import html
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ERROR: PyYAML is required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARKS = ROOT / "config" / "benchmarks.yaml"
USER_AGENT = "prism-router-benchmark-updater/0.1 (+https://github.com/pavneeta/prism-router)"
HTTP_TIMEOUT_S = 60

SWE_BENCH_URL = "https://www.swebench.com/index.html"
ARENA_DATASET_URL = "https://datasets-server.huggingface.co/rows"
ARENA_DATASET = "lmarena-ai/leaderboard-dataset"
TERMINAL_BENCH_URL = "https://www.tbench.ai/leaderboard/terminal-bench/2.0"
SWE_REBENCH_URL = "https://swe-rebench.com/"

# Catalog model id → DeepSWE leaderboard model slug(s), preferred first.
DEEPSWE_ALIASES: dict[str, list[str]] = {
    "openai/gpt-5.6-sol": ["gpt-5-6-sol", "gpt-5.6-sol"],
    "openai/gpt-5.6-terra": ["gpt-5-6-terra", "gpt-5.6-terra"],
    "openai/gpt-5.6-luna": ["gpt-5-6-luna", "gpt-5.6-luna"],
    "anthropic/claude-fable-5": ["claude-fable-5"],
    "anthropic/claude-opus-5": ["claude-opus-5"],
    "anthropic/claude-sonnet-5": ["claude-sonnet-5"],
    "moonshot/kimi-k3": ["kimi-k3"],
    "zai/glm-5.2": ["glm-5-2", "glm-5.2"],
    "deepseek/deepseek-v4-pro": ["deepseek-v4-pro"],
    "together/deepseek-v4-pro": ["deepseek-v4-pro"],
}

DEEPSWE_URLS = [
    "https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json",
    "https://deepswe.datacurve.ai/artifacts/leaderboard-live.json",
]

# Prefer max-effort rows when multiple configs exist for one model.
_EFFORT_RANK = {"max": 5, "xhigh": 4, "high": 3, "medium": 2, "default": 1, "low": 0}

logger = logging.getLogger("update_benchmarks")

# These aliases are deliberately exact. Do not add family-prefix matches:
# leaderboard variants can differ by release, effort, or agent harness.
ARENA_ALIASES: dict[str, list[str]] = {
    "openai/gpt-5.6-sol": ["gpt-5.6-sol-xhigh"],
    "openai/gpt-5.6-terra": ["gpt-5.6-terra-xhigh"],
    "openai/gpt-5.6-luna": ["gpt-5.6-luna-xhigh"],
    "anthropic/claude-fable-5": ["claude-fable-5-high"],
    "anthropic/claude-opus-5": ["claude-opus-5-max", "claude-opus-5-high"],
    "anthropic/claude-sonnet-5": ["claude-sonnet-5-high"],
    "moonshot/kimi-k3": ["kimi-k3-max"],
    "zai/glm-5.2": ["glm-5.2-max"],
    "deepseek/deepseek-v4-pro": ["deepseek-v4-pro"],
    "together/deepseek-v4-pro": ["deepseek-v4-pro"],
    "minimax/minimax-m3": ["minimax-m3"],
    "meta-llama/llama-4-maverick": ["llama-4-maverick-17b-128e-instruct"],
    "meta-llama/llama-4-scout": ["llama-4-scout-17b-16e-instruct"],
    "meta-llama/llama-3.3-70b-instruct": ["llama-3.3-70b-instruct"],
    "openai/gpt-4o": ["gpt-4o-2024-08-06"],
    "openai/gpt-4o-mini": ["gpt-4o-mini-2024-07-18"],
}

SWE_BENCH_ALIASES = {
    "gpt-4o-20241120": "openai/gpt-4o",
    "llama-4-maverick-instruct": "meta-llama/llama-4-maverick",
    "llama-4-scout-instruct": "meta-llama/llama-4-scout",
}

TERMINAL_BENCH_ALIASES = {
    "GPT-5.6 Sol": "openai/gpt-5.6-sol",
    "GPT-5.6 Terra": "openai/gpt-5.6-terra",
    "GPT-5.6 Luna": "openai/gpt-5.6-luna",
    "Fable 5": "anthropic/claude-fable-5",
    "Opus 5": "anthropic/claude-opus-5",
    "Sonnet 5": "anthropic/claude-sonnet-5",
}

SWE_REBENCH_ALIASES: dict[str, list[str]] = {
    "Fable 5 [high]": ["anthropic/claude-fable-5"],
    "Opus 5 [high]": ["anthropic/claude-opus-5"],
    "Sonnet 5 [high]": ["anthropic/claude-sonnet-5"],
    "GPT-5.6 Sol [medium]": ["openai/gpt-5.6-sol"],
    "GPT-5.6 Luna [medium]": ["openai/gpt-5.6-luna"],
    "GLM-5.2 [high]": ["zai/glm-5.2"],
    "DeepSeek-V4 Pro [high]": ["deepseek/deepseek-v4-pro", "together/deepseek-v4-pro"],
    "MiniMax M3": ["minimax/minimax-m3"],
}


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


def _http_get_text(url: str, headers: dict[str, str] | None = None) -> str:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*"}
    request_headers.update(headers or {})
    req = Request(url, headers=request_headers)
    with urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
        return resp.read().decode("utf-8", errors="replace")


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
    """Try AA's documented endpoint without a key; never read provider secrets."""
    urls = ["https://artificialanalysis.ai/api/v2/language/models"]
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
        "skip: documented Artificial Analysis Data API requires an x-api-key; "
        "no key was used (public webpage is not a stable machine-readable feed)",
        meta={
            "url": "https://artificialanalysis.ai/data-api/docs",
            "current_index_version": "4.3.2",
        },
    )


def _parse_aa_payload(payload: Any) -> dict[str, float]:
    aliases = {
        "claude-opus-5": "anthropic/claude-opus-5",
        "claude-sonnet-5": "anthropic/claude-sonnet-5",
        "gpt-5.6-sol": "openai/gpt-5.6-sol",
        "kimi-k3": "moonshot/kimi-k3",
        "glm-5.2": "zai/glm-5.2",
        "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
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
        name = str(row.get("slug") or row.get("model") or row.get("name") or "").lower()
        normalized = re.sub(r"[^a-z0-9.]+", "-", name).strip("-")
        evaluations = row.get("evaluations") if isinstance(row.get("evaluations"), dict) else {}
        idx = (
            row.get("artificial_analysis_intelligence_index")
            or row.get("intelligence_index")
            or row.get("aa_intelligence_index")
            or evaluations.get("artificial_analysis_intelligence_index")
        )
        if idx is None:
            continue
        for key, catalog_id in aliases.items():
            if normalized == key:
                out[catalog_id] = float(idx)
                break
    return out


def _parse_arena_payload(payload: Any, category: str = "overall") -> dict[str, float]:
    """Parse exact model/config matches from the official LMArena dataset."""
    if not isinstance(payload, dict):
        return {}
    rows: list[dict[str, Any]] = []
    for item in payload.get("rows") or []:
        if isinstance(item, dict) and isinstance(item.get("row"), dict):
            rows.append(item["row"])
    out: dict[str, float] = {}
    by_name = {
        str(row.get("model_name") or "").strip().lower(): row
        for row in rows
        if str(row.get("category") or "").lower() == category
    }
    for catalog_id, aliases in ARENA_ALIASES.items():
        for alias in aliases:
            row = by_name.get(alias.lower())
            if row is not None and row.get("rating") is not None:
                out[catalog_id] = round(float(row["rating"]), 3)
                break
    return out


def fetch_arena(category: str, source_key: str) -> SourceResult:
    """Fetch one category from LMArena's official public HF dataset."""
    collected: list[dict[str, Any]] = []
    seen_category = False
    snapshot_dates: list[str] = []
    try:
        # Rows are grouped by category. Stop after leaving the requested group.
        for offset in range(0, 2500, 100):
            query = urlencode(
                {
                    "dataset": ARENA_DATASET,
                    "config": "text_style_control",
                    "split": "latest",
                    "offset": offset,
                    "length": 100,
                }
            )
            payload = _http_get_json(f"{ARENA_DATASET_URL}?{query}")
            page_rows = payload.get("rows") if isinstance(payload, dict) else None
            if not page_rows:
                break
            page_categories = {
                str(item.get("row", {}).get("category") or "").lower()
                for item in page_rows
                if isinstance(item, dict)
            }
            matching = [
                item
                for item in page_rows
                if isinstance(item, dict)
                and str(item.get("row", {}).get("category") or "").lower() == category
            ]
            if matching:
                seen_category = True
                collected.extend(matching)
                snapshot_dates.extend(
                    str(item["row"].get("leaderboard_publish_date") or "")
                    for item in matching
                )
            elif seen_category and category not in page_categories:
                break
        scores = _parse_arena_payload({"rows": collected}, category)
        if not scores:
            return SourceResult(source_key, False, f"skip: no exact catalog matches in Arena {category}")
        snapshot = max((d for d in snapshot_dates if d), default="")
        return SourceResult(
            source_key,
            True,
            f"official LMArena {category} snapshot {snapshot} from {ARENA_DATASET_URL}",
            scores=scores,
            meta={"url": ARENA_DATASET_URL, "snapshot_date": snapshot, "category": category},
        )
    except Exception as exc:  # noqa: BLE001
        return SourceResult(source_key, False, f"skip: LMArena {category} unavailable ({exc})")


def fetch_arena_elo() -> SourceResult:
    return fetch_arena("overall", "arena_elo")


def fetch_arena_coding_elo() -> SourceResult:
    return fetch_arena("coding", "arena_coding_elo")


def fetch_swe_bench_verified() -> SourceResult:
    """Fetch comparable mini-SWE-agent rows from the official leaderboard."""
    try:
        page = _http_get_text(SWE_BENCH_URL)
        match = re.search(
            r'<script[^>]+id=["\']leaderboard-data["\'][^>]*>(.*?)</script>',
            page,
            re.DOTALL,
        )
        if not match:
            raise ValueError("leaderboard-data payload missing")
        payload = json.loads(html.unescape(match.group(1)))
        scores = _parse_swe_payload(payload)
        if not scores:
            raise ValueError("no exact mini-SWE-agent catalog matches")
        return SourceResult(
            "swe_bench_verified",
            True,
            f"official mini-SWE-agent rows from {SWE_BENCH_URL}",
            scores=scores,
            meta={"url": SWE_BENCH_URL, "harness": "mini-SWE-agent"},
        )
    except Exception as exc:  # noqa: BLE001
        return SourceResult("swe_bench_verified", False, f"skip: official leaderboard unavailable ({exc})")


def _parse_swe_payload(payload: Any) -> dict[str, float]:
    rows: list[dict[str, Any]] = []
    if isinstance(payload, list):
        # Official page payload: a list of leaderboard objects.
        for board in payload:
            if isinstance(board, dict) and str(board.get("name") or "").lower() == "verified":
                rows = [r for r in board.get("results") or [] if isinstance(r, dict)]
                break
    elif isinstance(payload, dict):
        rows = [r for r in payload.get("results") or [] if isinstance(r, dict)]
    out: dict[str, float] = {}
    for row in rows:
        if str(row.get("agent") or "").lower() != "mini-swe-agent":
            continue
        tags = row.get("tags") or []
        model_tags = [
            str(tag).split(":", 1)[1].strip().lower()
            for tag in tags
            if isinstance(tag, str) and tag.lower().startswith("model:")
        ]
        score = row.get("resolved")
        if score is None:
            continue
        val = float(score)
        if val > 1.0:
            val = val / 100.0
        for model_tag in model_tags:
            catalog_id = SWE_BENCH_ALIASES.get(model_tag)
            if catalog_id:
                out[catalog_id] = round(val, 3)
                break
    return out


def fetch_terminal_bench() -> SourceResult:
    """Fetch the official Terminal-Bench 2.0 leaderboard RSC payload."""
    path = "/leaderboard/terminal-bench/2.0"
    try:
        text = _http_get_text(TERMINAL_BENCH_URL, {"RSC": "1", "Next-Url": path})
        marker = '"rows":['
        start = text.find(marker)
        if start < 0:
            raise ValueError("rows payload missing")
        rows, _ = json.JSONDecoder().raw_decode(text[start + len('"rows":') :])
        scores = _parse_terminal_payload(rows)
        if not scores:
            raise ValueError("no exact catalog model/config matches")
        dates = [
            str(row.get("metadata", {}).get("date") or "")
            for row in rows
            if isinstance(row, dict)
        ]
        data_date = max((d for d in dates if d), default="")
        return SourceResult(
            "terminal_bench_2",
            True,
            f"official Terminal-Bench 2.0 leaderboard through {data_date} from {TERMINAL_BENCH_URL}",
            scores=scores,
            meta={"url": TERMINAL_BENCH_URL, "data_through": data_date},
        )
    except Exception as exc:  # noqa: BLE001
        return SourceResult("terminal_bench_2", False, f"skip: official leaderboard unavailable ({exc})")


def _parse_terminal_payload(payload: Any) -> dict[str, float]:
    if isinstance(payload, dict):
        rows = payload.get("results") or payload.get("models") or payload.get("leaderboard") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        return {}
    chosen: dict[str, tuple[int, float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        display = metadata.get("model_display")
        if isinstance(display, dict):
            name = str(display.get("label") or "")
        else:
            name = str(row.get("model") or row.get("name") or "")
        catalog_id = TERMINAL_BENCH_ALIASES.get(name)
        if catalog_id is None:
            continue
        score = metrics.get("accuracy")
        if score is None:
            score = row.get("score") or row.get("pass_at_1") or row.get("accuracy")
        if score is None:
            continue
        val = float(score)
        if val > 1.0:
            val = val / 100.0
        effort = str(metadata.get("reasoning_effort") or row.get("reasoning_effort") or "default").lower()
        candidate = (_EFFORT_RANK.get(effort, -1), val)
        if candidate > chosen.get(catalog_id, (-2, -1.0)):
            chosen[catalog_id] = candidate
    return {catalog_id: round(value, 3) for catalog_id, (_, value) in chosen.items()}


def _parse_swe_rebench_payload(text: str) -> tuple[dict[str, float], str]:
    """Parse exact model rows from SWE-rebench's public Next.js payload.

    The page can embed multiple windows for one model. Keep the latest
    ``taskRangeTimestamp.to`` rather than the first regex hit.
    """
    scores: dict[str, float] = {}
    chosen_end: dict[str, int] = {}
    snapshot = ""
    for display_name, catalog_ids in SWE_REBENCH_ALIASES.items():
        escaped_name = re.escape(json.dumps(display_name)[1:-1])
        name_pat = re.compile(rf'\\"modelName\\":\\"{escaped_name}\\"')
        for name_match in name_pat.finditer(text):
            window = text[name_match.end() : name_match.end() + 20000]
            ts = re.search(
                r'\\"taskRangeTimestamp\\":\{\\"from\\":(\d+),\\"to\\":(\d+)\}',
                window,
            )
            if not ts:
                continue
            start_ms, end_ms = ts.groups()
            end_i = int(end_ms)
            rate = re.search(
                rf'\\"{re.escape(start_ms)}:{re.escape(end_ms)}\\":\{{\\"resolvedRate\\":([0-9.]+)',
                window,
            )
            if not rate:
                continue
            value = round(float(rate.group(1)) / 100.0, 3)
            day = datetime.fromtimestamp(end_i / 1000, tz=timezone.utc).date().isoformat()
            for catalog_id in catalog_ids:
                if end_i >= chosen_end.get(catalog_id, -1):
                    scores[catalog_id] = value
                    chosen_end[catalog_id] = end_i
                    snapshot = max(snapshot, day)
    return scores, snapshot


def fetch_swe_rebench() -> SourceResult:
    try:
        text = _http_get_text(SWE_REBENCH_URL)
        scores, snapshot = _parse_swe_rebench_payload(text)
        if not scores:
            raise ValueError("no exact catalog rows found")
        return SourceResult(
            "swe_rebench_resolved",
            True,
            f"latest public window ending {snapshot} from {SWE_REBENCH_URL}",
            scores=scores,
            meta={"url": SWE_REBENCH_URL, "snapshot_date": snapshot, "metric": "Resolved Rate"},
        )
    except Exception as exc:  # noqa: BLE001
        return SourceResult("swe_rebench_resolved", False, f"skip: public page unavailable ({exc})")


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


def insert_source_value(text: str, model_id: str, source_key: str, new_value: Any) -> tuple[str, bool]:
    """Insert a new source key under an existing model ``sources:`` block."""
    model_pat = re.compile(
        rf"(^[ \t]*)({re.escape(model_id)}:)[ \t]*\n",
        re.MULTILINE,
    )
    m = model_pat.search(text)
    if not m:
        logger.warning("model %s not found in YAML; skip insert %s", model_id, source_key)
        return text, False
    start = m.end()
    next_model = re.search(r"\n  [^\s#].*:\s*(?:#.*)?\n", text[start:])
    end = start + next_model.start() + 1 if next_model else len(text)
    block = text[start:end]
    sources = re.search(r"^([ \t]*)sources:\s*\n", block, re.MULTILINE)
    if not sources:
        logger.warning("sources block missing under %s; skip insert %s", model_id, source_key)
        return text, False
    indent = sources.group(1) + "  "
    insertion = f"{indent}{source_key}: {_format_source_value(new_value)}\n"
    insert_at = sources.end()
    new_block = block[:insert_at] + insertion + block[insert_at:]
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
                text, changed = insert_source_value(text, model_id, result.name, new_val)
            else:
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
        fetch_swe_rebench(),
        fetch_terminal_bench(),
        fetch_aa_intelligence_index(),
        fetch_arena_elo(),
        fetch_arena_coding_elo(),
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
