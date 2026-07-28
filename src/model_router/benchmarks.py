from __future__ import annotations

from typing import Any

from model_router.config import ModelBenchmark


AA_INDEX_DENOMINATOR = 70.0  # top AA Index ~61 → ~0.87
ARENA_ELO_FLOOR = 1000.0
ARENA_ELO_SPAN = 550.0


def normalize_aa_index(index: float | None) -> float | None:
    if index is None:
        return None
    return max(0.0, min(1.0, float(index) / AA_INDEX_DENOMINATOR))


def normalize_arena_elo(elo: float | None) -> float | None:
    if elo is None:
        return None
    return max(0.0, min(1.0, (float(elo) - ARENA_ELO_FLOOR) / ARENA_ELO_SPAN))


def derive_task_accuracy(sources: dict[str, Any]) -> dict[str, float]:
    """Map public leaderboard metrics → router task accuracies in [0, 1]."""
    deepswe = sources.get("deepswe")
    swe = sources.get("swe_bench_verified")
    terminal = sources.get("terminal_bench_v2_1")
    aa_norm = normalize_aa_index(sources.get("aa_intelligence_index"))
    arena_norm = normalize_arena_elo(sources.get("arena_elo"))

    # Prefer DeepSWE for codegen. Do not fall back to SWE-bench alone — that
    # metric is more saturated and inflates models missing DeepSWE rows
    # (e.g. DeepSeek V4 Pro) above Fable/Kimi peers.
    code_gen = float(deepswe) if deepswe is not None else None
    code_debug = float(swe) if swe is not None else (float(deepswe) if deepswe is not None else None)

    chat_prior = arena_norm if arena_norm is not None else aa_norm
    if aa_norm is not None and arena_norm is not None:
        knowledge = 0.6 * aa_norm + 0.4 * arena_norm
    else:
        knowledge = aa_norm if aa_norm is not None else arena_norm

    out: dict[str, float] = {}
    if code_gen is not None:
        out["code_generation"] = round(code_gen, 4)
    if code_debug is not None:
        out["code_review_debug"] = round(code_debug, 4)
    if terminal is not None:
        out["tool_use_agent"] = round(float(terminal), 4)
    if aa_norm is not None:
        out["reasoning_math"] = round(aa_norm, 4)
    if knowledge is not None:
        out["summarization"] = round(knowledge, 4)
        out["extraction_qa"] = round(knowledge, 4)
    if chat_prior is not None:
        out["creative_writing"] = round(chat_prior, 4)
        out["general_chat"] = round(chat_prior, 4)
    return out


def materialize_accuracy(bench: ModelBenchmark) -> ModelBenchmark:
    """Fill accuracy from sources when accuracy is empty or partial."""
    derived = derive_task_accuracy(bench.sources)
    if not derived:
        return bench
    merged = {**derived, **bench.accuracy}  # explicit accuracy overrides derived
    return bench.model_copy(update={"accuracy": merged})
