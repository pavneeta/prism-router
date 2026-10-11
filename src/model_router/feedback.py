"""Append-only outcome feedback plus a fail-soft task×model pass-rate EWMA."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from model_router.config import get_settings
from model_router.telemetry import now_ts

_ALPHA = 0.2
_NEUTRAL_PASS = 0.7
_MAX_COST_TILT = 0.08


@dataclass(frozen=True)
class FeedbackEvent:
    ts: str
    session_id: str
    outcome: str  # pass | fail
    task_hint: str | None = None
    notes: str | None = None
    selected_model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FeedbackLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def append(self, event: FeedbackEvent) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(event.to_dict(), default=str) + "\n")
            except OSError:
                pass


class FeedbackAccuracy:
    """In-memory EWMA of pass rate keyed by (task_type, model_id).

    Used as a soft cost nudge after public intelligence floors are applied.
    Missing data is a no-op (multiplier 1.0).
    """

    def __init__(self, *, alpha: float = _ALPHA) -> None:
        self.alpha = alpha
        self._lock = threading.Lock()
        self._ewma: dict[tuple[str, str], float] = {}

    def reset(self) -> None:
        with self._lock:
            self._ewma.clear()

    def observe(self, *, task_type: str | None, model_id: str | None, passed: bool) -> None:
        if not task_type or not model_id:
            return
        key = (task_type, model_id)
        value = 1.0 if passed else 0.0
        with self._lock:
            prev = self._ewma.get(key, _NEUTRAL_PASS)
            self._ewma[key] = (1.0 - self.alpha) * prev + self.alpha * value

    def pass_rate(self, task_type: str, model_id: str) -> float | None:
        with self._lock:
            rate = self._ewma.get((task_type, model_id))
            return None if rate is None else float(rate)

    def cost_multiplier(self, task_type: str, model_id: str) -> float:
        rate = self.pass_rate(task_type, model_id)
        if rate is None:
            return 1.0
        tilt = (_NEUTRAL_PASS - rate) * 0.2
        return 1.0 + max(-_MAX_COST_TILT, min(_MAX_COST_TILT, tilt))

    def load_jsonl(self, path: Path) -> int:
        """Best-effort replay. Returns number of events consumed."""
        if not path.exists():
            return 0
        loaded = 0
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                outcome = str(row.get("outcome") or "").strip().lower()
                if outcome not in {"pass", "fail"}:
                    continue
                self.observe(
                    task_type=(row.get("task_hint") or "").strip() or None,
                    model_id=(
                        (row.get("selected_model") or row.get("model") or "").strip() or None
                    ),
                    passed=outcome == "pass",
                )
                loaded += 1
        except OSError:
            return loaded
        return loaded

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return {f"{task}|{model}": rate for (task, model), rate in self._ewma.items()}


_logger: FeedbackLogger | None = None
_accuracy: FeedbackAccuracy | None = None
_feedback_lock = threading.Lock()


def get_feedback_logger() -> FeedbackLogger:
    global _logger
    if _logger is None:
        settings = get_settings()
        path = Path(settings.model_router_feedback_path)
        _logger = FeedbackLogger(path)
    return _logger


def get_feedback_accuracy() -> FeedbackAccuracy:
    global _accuracy
    with _feedback_lock:
        if _accuracy is None:
            tracker = FeedbackAccuracy()
            try:
                settings = get_settings()
                tracker.load_jsonl(Path(settings.model_router_feedback_path))
            except Exception:
                pass
            _accuracy = tracker
        return _accuracy


def record_feedback(event: FeedbackEvent) -> None:
    get_feedback_logger().append(event)
    get_feedback_accuracy().observe(
        task_type=event.task_hint,
        model_id=event.selected_model,
        passed=event.outcome == "pass",
    )


def reset_feedback_logger_for_tests() -> None:
    global _logger, _accuracy
    with _feedback_lock:
        _logger = None
        _accuracy = None
