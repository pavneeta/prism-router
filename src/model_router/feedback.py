"""Append-only outcome feedback for offline benchmark loops (no online learning)."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from model_router.config import get_settings
from model_router.telemetry import now_ts


@dataclass(frozen=True)
class FeedbackEvent:
    ts: str
    session_id: str
    outcome: str  # pass | fail
    task_hint: str | None = None
    notes: str | None = None

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


_logger: FeedbackLogger | None = None


def get_feedback_logger() -> FeedbackLogger:
    global _logger
    if _logger is None:
        settings = get_settings()
        path = Path(settings.model_router_feedback_path)
        _logger = FeedbackLogger(path)
    return _logger


def reset_feedback_logger_for_tests() -> None:
    global _logger
    _logger = None
