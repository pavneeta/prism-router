"""In-process token usage aggregation (per session / model / provider).

v1 is process-local: with multiple gateway replicas (e.g. Railway numReplicas=2)
each replica only sees its own traffic. Shared Redis/store is a follow-up.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class UsageTotals:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    request_count: int = 0
    est_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0

    def add(
        self,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cached_tokens: int = 0,
        est_cost_usd: float = 0.0,
        actual_cost_usd: float = 0.0,
        request_count: int = 1,
    ) -> None:
        self.prompt_tokens += max(0, int(prompt_tokens or 0))
        self.completion_tokens += max(0, int(completion_tokens or 0))
        self.cached_tokens += max(0, int(cached_tokens or 0))
        self.total_tokens = self.prompt_tokens + self.completion_tokens
        self.request_count += max(0, int(request_count or 0))
        self.est_cost_usd += float(est_cost_usd or 0.0)
        self.actual_cost_usd += float(actual_cost_usd or 0.0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _UsageRecord:
    session_id: str | None
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    est_cost_usd: float
    actual_cost_usd: float


def _empty() -> UsageTotals:
    return UsageTotals()


class UsageMetricsStore:
    """Thread-safe in-memory usage rollups."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[_UsageRecord] = []

    def reset(self) -> None:
        with self._lock:
            self._records.clear()

    def record(
        self,
        *,
        session_id: str | None,
        model: str,
        provider: str,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        cached_tokens: int | None = None,
        est_cost_usd: float | None = None,
        actual_cost_usd: float | None = None,
    ) -> None:
        rec = _UsageRecord(
            session_id=session_id or None,
            model=model or "unknown",
            provider=provider or "unknown",
            prompt_tokens=max(0, int(prompt_tokens or 0)),
            completion_tokens=max(0, int(completion_tokens or 0)),
            cached_tokens=max(0, int(cached_tokens or 0)),
            est_cost_usd=float(est_cost_usd or 0.0),
            actual_cost_usd=float(actual_cost_usd or 0.0),
        )
        with self._lock:
            self._records.append(rec)

    def snapshot(
        self,
        *,
        session_id: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            records = list(self._records)

        def _match(rec: _UsageRecord) -> bool:
            if session_id is not None and rec.session_id != session_id:
                return False
            if model is not None and rec.model != model:
                return False
            if provider is not None and rec.provider != provider:
                return False
            return True

        matched = [r for r in records if _match(r)]
        totals = _empty()
        by_session: dict[str, UsageTotals] = {}
        by_model: dict[str, UsageTotals] = {}
        by_provider: dict[str, UsageTotals] = {}

        for rec in matched:
            kwargs = {
                "prompt_tokens": rec.prompt_tokens,
                "completion_tokens": rec.completion_tokens,
                "cached_tokens": rec.cached_tokens,
                "est_cost_usd": rec.est_cost_usd,
                "actual_cost_usd": rec.actual_cost_usd,
                "request_count": 1,
            }
            totals.add(**kwargs)
            if rec.session_id:
                by_session.setdefault(rec.session_id, _empty()).add(**kwargs)
            by_model.setdefault(rec.model, _empty()).add(**kwargs)
            by_provider.setdefault(rec.provider, _empty()).add(**kwargs)

        return {
            "scope": "in_process",
            "note": (
                "Usage metrics are aggregated in-memory per gateway process. "
                "With multiple replicas (e.g. Railway numReplicas=2), each replica "
                "only reports its own traffic — totals are not cluster-wide. "
                "Shared store (Redis) is a follow-up."
            ),
            "filters": {
                "session_id": session_id,
                "model": model,
                "provider": provider,
            },
            "totals": totals.to_dict(),
            "by_session": {k: v.to_dict() for k, v in by_session.items()},
            "by_model": {k: v.to_dict() for k, v in by_model.items()},
            "by_provider": {k: v.to_dict() for k, v in by_provider.items()},
        }


_default_usage_metrics = UsageMetricsStore()


def get_usage_metrics() -> UsageMetricsStore:
    return _default_usage_metrics


def reset_usage_metrics_for_tests() -> None:
    _default_usage_metrics.reset()
