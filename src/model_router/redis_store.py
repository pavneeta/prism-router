"""Optional Redis backing for cross-replica session affinity and local cache."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

logger = logging.getLogger("model_router.redis")

_client: Any | None = None
_client_url: str | None = None
_lock = threading.Lock()


def get_redis_client(redis_url: str | None) -> Any | None:
    """Return a shared Redis client or None when URL unset / package missing."""
    global _client, _client_url
    url = (redis_url or "").strip()
    if not url:
        with _lock:
            _client = None
            _client_url = None
        return None
    with _lock:
        if _client is not None and _client_url == url:
            return _client
        try:
            import redis
        except ImportError:
            logger.warning(
                "MODEL_ROUTER_REDIS_URL is set but redis package is not installed; "
                "using in-memory session store"
            )
            _client = None
            _client_url = url
            return None
        try:
            _client = redis.from_url(url, decode_responses=True)
            _client.ping()
            _client_url = url
            logger.info("redis connected for shared affinity/cache")
            return _client
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis unavailable (%s); falling back to in-memory", exc)
            _client = None
            _client_url = url
            return None


def reset_redis_client_for_tests() -> None:
    global _client, _client_url
    with _lock:
        _client = None
        _client_url = None


def redis_get_json(client: Any, key: str) -> dict[str, Any] | None:
    raw = client.get(key)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def redis_set_json(client: Any, key: str, payload: dict[str, Any], *, ttl_seconds: float) -> None:
    client.setex(key, max(1, int(ttl_seconds)), json.dumps(payload, default=str))
