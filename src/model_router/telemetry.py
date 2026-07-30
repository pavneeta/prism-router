from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from model_router.safety import redact_secrets

logger = logging.getLogger(__name__)


@dataclass
class TelemetryEvent:
    ts: float
    request_id: str
    session_id: str | None
    route_mode: str
    requested_model: str
    selected_model: str
    litellm_model: str
    task_type: str
    classification_confidence: float
    classification_signals: list[str]
    policy_reason: str
    estimated_cost_usd: float
    frontier_cost_usd: float
    cost_delta_vs_frontier_usd: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None
    actual_cost_usd: float | None = None
    latency_ms: float | None = None
    status: str = "ok"
    error: str | None = None
    cache_hit: bool = False
    cache_layer: str = "none"
    estimated_cached_tokens: int = 0
    sticky_model: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class TelemetryLogger:
    """Append-only JSONL telemetry. Never raises — ephemeral FS / disk full must not crash requests."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._ensure_parent()

    def _ensure_parent(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            return True
        except OSError as exc:
            logger.warning("telemetry: cannot create dir %s: %s", self.path.parent, exc)
            return False

    def emit(self, event: TelemetryEvent) -> None:
        if event.error:
            event.error = redact_secrets(event.error)
        if not self._ensure_parent():
            return
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(event), default=str) + "\n")
        except OSError as exc:
            logger.warning("telemetry: write failed %s: %s", self.path, exc)


def now_ts() -> float:
    return time.time()
