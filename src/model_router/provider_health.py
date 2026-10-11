"""Minimal EWMA provider error rates from gateway telemetry."""

from __future__ import annotations

import threading
from typing import Any

from model_router.litellm_backend import provider_type

_ALPHA = 0.15


class ProviderHealthTracker:
    """In-process EWMA failure rate per provider family (openai, anthropic, …)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ewma: dict[str, float] = {}

    def reset(self) -> None:
        with self._lock:
            self._ewma.clear()

    def record(self, *, litellm_model: str, success: bool) -> None:
        provider = provider_type(litellm_model)
        failure = 0.0 if success else 1.0
        with self._lock:
            prev = self._ewma.get(provider, 0.0)
            self._ewma[provider] = (1.0 - _ALPHA) * prev + _ALPHA * failure

    def error_rate(self, litellm_model: str) -> float:
        provider = provider_type(litellm_model)
        with self._lock:
            return float(self._ewma.get(provider, 0.0))

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return dict(self._ewma)


_default: ProviderHealthTracker | None = None
_health_lock = threading.Lock()


def get_provider_health() -> ProviderHealthTracker:
    global _default
    with _health_lock:
        if _default is None:
            _default = ProviderHealthTracker()
        return _default


def reset_provider_health_for_tests() -> None:
    global _default
    with _health_lock:
        if _default is not None:
            _default.reset()
