"""Session-aware task classification and telemetry rollups."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from model_router.classifier import Classification


def _harder(a: str, b: str) -> str:
    return "hard" if "hard" in (a, b) else "easy"


@dataclass
class SessionTaskState:
    task_type: str
    confidence: float
    updated_at: float
    turns: int = 1
    difficulty: str = "easy"


@dataclass
class SessionRollup:
    session_id: str
    started_at: float
    updated_at: float
    request_count: int = 0
    total_latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    frontier_cost_usd: float = 0.0
    cost_delta_vs_frontier_usd: float = 0.0
    cache_hits: int = 0
    routing_turns: int = 0
    affinity_preserves: int = 0
    estimated_cache_savings_usd: float = 0.0
    task_types: dict[str, int] = field(default_factory=dict)
    selected_models: dict[str, int] = field(default_factory=dict)
    last_task_type: str | None = None
    last_selected_model: str | None = None

    def sticky_ratio(self) -> float | None:
        if self.routing_turns <= 0:
            return None
        return self.affinity_preserves / self.routing_turns

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["wall_time_s"] = max(0.0, self.updated_at - self.started_at)
        ratio = self.sticky_ratio()
        if ratio is not None:
            d["observed_sticky_ratio"] = ratio
        return d


class SessionStore:
    """In-memory session task memory + cost/token rollups."""

    def __init__(self, *, ttl_seconds: float = 1800.0, rollup_path: Path | None = None) -> None:
        self.ttl_seconds = ttl_seconds
        self.rollup_path = rollup_path
        self._tasks: dict[str, SessionTaskState] = {}
        self._rollups: dict[str, SessionRollup] = {}
        self._lock = threading.Lock()

    def get_task(self, session_id: str | None) -> SessionTaskState | None:
        if not session_id:
            return None
        now = time.time()
        with self._lock:
            state = self._tasks.get(session_id)
            if state is None:
                return None
            if now - state.updated_at > self.ttl_seconds:
                del self._tasks[session_id]
                return None
            return state

    def set_task(self, session_id: str | None, classification: Classification) -> None:
        if not session_id:
            return
        now = time.time()
        with self._lock:
            prev = self._tasks.get(session_id)
            if prev and prev.task_type == classification.task_type:
                prev.confidence = max(prev.confidence, classification.confidence)
                prev.difficulty = _harder(prev.difficulty, classification.difficulty)
                prev.updated_at = now
                prev.turns += 1
            else:
                self._tasks[session_id] = SessionTaskState(
                    task_type=classification.task_type,
                    confidence=classification.confidence,
                    updated_at=now,
                    turns=(prev.turns + 1) if prev else 1,
                    difficulty=classification.difficulty,
                )

    def record_event(
        self,
        *,
        session_id: str | None,
        task_type: str,
        selected_model: str,
        latency_ms: float | None,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        estimated_cost_usd: float,
        actual_cost_usd: float | None,
        frontier_cost_usd: float,
        cost_delta_vs_frontier_usd: float,
        cache_hit: bool,
        estimated_cached_tokens: int,
        input_cost_per_m: float | None = None,
    ) -> SessionRollup | None:
        if not session_id:
            return None
        now = time.time()
        with self._lock:
            rollup = self._rollups.get(session_id)
            if rollup is None:
                rollup = SessionRollup(session_id=session_id, started_at=now, updated_at=now)
                self._rollups[session_id] = rollup
            rollup.updated_at = now
            rollup.request_count += 1
            rollup.total_latency_ms += float(latency_ms or 0.0)
            rollup.prompt_tokens += int(prompt_tokens or 0)
            rollup.completion_tokens += int(completion_tokens or 0)
            rollup.estimated_cost_usd += float(estimated_cost_usd or 0.0)
            rollup.actual_cost_usd += float(actual_cost_usd or 0.0)
            rollup.frontier_cost_usd += float(frontier_cost_usd or 0.0)
            rollup.cost_delta_vs_frontier_usd += float(cost_delta_vs_frontier_usd or 0.0)
            if cache_hit:
                rollup.cache_hits += 1
            # Approx savings vs full-price input for cached tokens (50% if rate unknown)
            if estimated_cached_tokens > 0:
                rate = input_cost_per_m if input_cost_per_m is not None else 1.0
                # cached typically ~half; savings ≈ half of cached token list cost
                rollup.estimated_cache_savings_usd += (
                    estimated_cached_tokens / 1_000_000.0
                ) * (rate * 0.5)
            rollup.task_types[task_type] = rollup.task_types.get(task_type, 0) + 1
            rollup.selected_models[selected_model] = (
                rollup.selected_models.get(selected_model, 0) + 1
            )
            rollup.last_task_type = task_type
            rollup.last_selected_model = selected_model
            self._persist(rollup)
            return rollup

    def get_rollup(self, session_id: str) -> SessionRollup | None:
        with self._lock:
            return self._rollups.get(session_id)

    def observed_sticky_ratio(self, session_id: str | None) -> float | None:
        if not session_id:
            return None
        with self._lock:
            rollup = self._rollups.get(session_id)
            if rollup is None:
                return None
            return rollup.sticky_ratio()

    def record_routing_turn(self, session_id: str | None, *, affinity_preserve: bool) -> None:
        if not session_id:
            return
        now = time.time()
        with self._lock:
            rollup = self._rollups.get(session_id)
            if rollup is None:
                rollup = SessionRollup(session_id=session_id, started_at=now, updated_at=now)
                self._rollups[session_id] = rollup
            rollup.updated_at = now
            rollup.routing_turns += 1
            if affinity_preserve:
                rollup.affinity_preserves += 1

    def _persist(self, rollup: SessionRollup) -> None:
        if self.rollup_path is None:
            return
        try:
            self.rollup_path.parent.mkdir(parents=True, exist_ok=True)
            # Append latest rollup snapshot (ephemeral FS may fail — ignore)
            with self.rollup_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rollup.to_dict(), default=str) + "\n")
        except OSError:
            pass


_default_sessions = SessionStore(rollup_path=Path("logs/session_rollups.jsonl"))


def get_session_store() -> SessionStore:
    return _default_sessions


def apply_session_classification(
    turn: Classification,
    *,
    prior: SessionTaskState | None,
    drift_confidence: float = 0.80,
) -> Classification:
    """Stick to prior session task unless the new turn is confident and different."""
    if prior is None:
        return turn

    signals = list(turn.signals)
    signals.append("session_prior:" + prior.task_type)

    # Strong new signal → allow drift
    if turn.task_type != prior.task_type and turn.confidence >= drift_confidence:
        signals.append("session_task_drift")
        return Classification(
            turn.task_type,
            turn.confidence,
            signals,
            difficulty=turn.difficulty,
        )

    # Otherwise keep session task, blend confidence upward slightly
    if turn.task_type == prior.task_type:
        signals.append("session_task_confirm")
        return Classification(
            prior.task_type,
            max(prior.confidence, turn.confidence),
            signals,
            difficulty=_harder(prior.difficulty, turn.difficulty),
        )

    # Weak disagreement → keep prior
    signals.append("session_task_hold")
    return Classification(
        prior.task_type,
        max(0.55, min(prior.confidence, 0.85)),
        signals,
        difficulty=prior.difficulty,
    )
