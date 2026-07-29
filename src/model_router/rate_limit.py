"""Simple in-process sliding-window rate limiter (per key, usually client IP).

Not shared across Railway replicas — use edge/Railway rate limits for hard caps.
Set ``MODEL_ROUTER_RATE_LIMIT_RPM=0`` to disable.
"""

from __future__ import annotations

import threading
import time


class InProcessRateLimiter:
    def __init__(self, rpm: int = 0) -> None:
        self.rpm = max(0, int(rpm))
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def configure(self, rpm: int) -> None:
        with self._lock:
            self.rpm = max(0, int(rpm))

    def allow(self, key: str) -> bool:
        if self.rpm <= 0:
            return True
        now = time.time()
        window = 60.0
        with self._lock:
            hits = self._hits.setdefault(key, [])
            hits[:] = [t for t in hits if now - t < window]
            if len(hits) >= self.rpm:
                return False
            hits.append(now)
            # Opportunistic prune of idle keys
            if len(self._hits) > 10_000:
                stale = [k for k, v in self._hits.items() if not v]
                for k in stale[:1000]:
                    self._hits.pop(k, None)
            return True


_limiter = InProcessRateLimiter()


def get_rate_limiter() -> InProcessRateLimiter:
    return _limiter
