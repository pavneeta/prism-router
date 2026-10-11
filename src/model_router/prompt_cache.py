from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any

from model_router.redis_store import get_redis_client, redis_get_json, redis_set_json


@dataclass
class SessionAffinity:
    model_id: str
    litellm_model: str
    prefix_tokens_estimate: int
    updated_at: float


@dataclass
class LocalCacheEntry:
    response: dict[str, Any]
    created_at: float
    hits: int = 0


@dataclass
class CacheLookupResult:
    hit: bool
    layer: str  # local | none
    response: dict[str, Any] | None = None


class PromptCacheLayer:
    """Local exact-match cache + session affinity (in-memory or Redis-backed)."""

    _AFFINITY_PREFIX = "prism:affinity:"
    _LOCAL_PREFIX = "prism:local:"

    def __init__(
        self,
        *,
        enabled: bool = True,
        ttl_seconds: float = 300.0,
        max_entries: int = 2048,
        affinity_ttl_seconds: float = 1800.0,
        redis_url: str | None = None,
        shared_local_cache: bool = False,
    ) -> None:
        self.enabled = enabled
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.affinity_ttl_seconds = affinity_ttl_seconds
        self.shared_local_cache = shared_local_cache
        self._local: dict[str, LocalCacheEntry] = {}
        self._affinity: dict[str, SessionAffinity] = {}
        self._lock = threading.Lock()
        self._redis = get_redis_client(redis_url)
        self._redis_url = (redis_url or "").strip()

    def backend(self) -> str:
        if self._redis is not None:
            return "redis"
        if self._redis_url:
            return "redis_unavailable"
        return "in_memory"

    def configure(
        self,
        *,
        enabled: bool | None = None,
        ttl_seconds: float | None = None,
        affinity_ttl_seconds: float | None = None,
        redis_url: str | None = None,
        shared_local_cache: bool | None = None,
    ) -> None:
        """Apply policy.yaml knobs without dropping existing entries."""
        with self._lock:
            if enabled is not None:
                self.enabled = enabled
            if ttl_seconds is not None:
                self.ttl_seconds = ttl_seconds
            if affinity_ttl_seconds is not None:
                self.affinity_ttl_seconds = affinity_ttl_seconds
            if shared_local_cache is not None:
                self.shared_local_cache = shared_local_cache
        if redis_url is not None:
            self._redis_url = redis_url.strip()
            self._redis = get_redis_client(self._redis_url or None)

    def clear(self) -> None:
        with self._lock:
            self._local.clear()
            self._affinity.clear()

    @staticmethod
    def request_key(
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _use_redis_local(self) -> bool:
        return self._redis is not None and self.shared_local_cache

    def get_local(self, key: str) -> CacheLookupResult:
        if not self.enabled:
            return CacheLookupResult(hit=False, layer="none")
        now = time.time()
        if self._use_redis_local():
            assert self._redis is not None
            data = redis_get_json(self._redis, self._LOCAL_PREFIX + key)
            if data is None:
                return CacheLookupResult(hit=False, layer="none")
            created = float(data.get("created_at", 0))
            if now - created > self.ttl_seconds:
                self._redis.delete(self._LOCAL_PREFIX + key)
                return CacheLookupResult(hit=False, layer="none")
            return CacheLookupResult(hit=True, layer="local", response=data.get("response"))
        with self._lock:
            entry = self._local.get(key)
            if entry is None:
                return CacheLookupResult(hit=False, layer="none")
            if now - entry.created_at > self.ttl_seconds:
                del self._local[key]
                return CacheLookupResult(hit=False, layer="none")
            entry.hits += 1
            return CacheLookupResult(hit=True, layer="local", response=entry.response)

    def put_local(self, key: str, response: dict[str, Any]) -> None:
        if not self.enabled:
            return
        now = time.time()
        if self._use_redis_local():
            assert self._redis is not None
            redis_set_json(
                self._redis,
                self._LOCAL_PREFIX + key,
                {"response": response, "created_at": now},
                ttl_seconds=self.ttl_seconds,
            )
            return
        with self._lock:
            if len(self._local) >= self.max_entries:
                oldest = min(self._local.items(), key=lambda kv: kv[1].created_at)
                del self._local[oldest[0]]
            self._local[key] = LocalCacheEntry(response=response, created_at=now)

    def get_affinity(self, session_id: str | None) -> SessionAffinity | None:
        if not session_id:
            return None
        now = time.time()
        if self._redis is not None:
            data = redis_get_json(self._redis, self._AFFINITY_PREFIX + session_id)
            if data is None:
                return None
            updated = float(data.get("updated_at", 0))
            if now - updated > self.affinity_ttl_seconds:
                self._redis.delete(self._AFFINITY_PREFIX + session_id)
                return None
            return SessionAffinity(
                model_id=str(data["model_id"]),
                litellm_model=str(data["litellm_model"]),
                prefix_tokens_estimate=int(data.get("prefix_tokens_estimate", 0)),
                updated_at=updated,
            )
        with self._lock:
            entry = self._affinity.get(session_id)
            if entry is None:
                return None
            if now - entry.updated_at > self.affinity_ttl_seconds:
                del self._affinity[session_id]
                return None
            return entry

    def set_affinity(
        self,
        session_id: str | None,
        *,
        model_id: str,
        litellm_model: str,
        prefix_tokens_estimate: int,
    ) -> None:
        if not session_id:
            return
        now = time.time()
        if self._redis is not None:
            redis_set_json(
                self._redis,
                self._AFFINITY_PREFIX + session_id,
                {
                    "model_id": model_id,
                    "litellm_model": litellm_model,
                    "prefix_tokens_estimate": prefix_tokens_estimate,
                    "updated_at": now,
                },
                ttl_seconds=self.affinity_ttl_seconds,
            )
            return
        with self._lock:
            self._affinity[session_id] = SessionAffinity(
                model_id=model_id,
                litellm_model=litellm_model,
                prefix_tokens_estimate=prefix_tokens_estimate,
                updated_at=now,
            )


_default_cache: PromptCacheLayer | None = None
_cache_policy_sig: tuple[Any, ...] | None = None
_cache_lock = threading.Lock()


def get_prompt_cache() -> PromptCacheLayer:
    """Process-wide cache; TTLs / enabled flag come from policy.yaml."""
    from model_router.config import get_settings, load_policy

    global _default_cache, _cache_policy_sig
    policy = load_policy()
    settings = get_settings()
    sig = (
        policy.prompt_cache_enabled,
        policy.local_cache_ttl_seconds,
        policy.session_affinity_ttl_seconds,
        policy.shared_local_cache_enabled,
        (settings.model_router_redis_url or "").strip(),
    )
    with _cache_lock:
        if _default_cache is None:
            _default_cache = PromptCacheLayer(
                enabled=policy.prompt_cache_enabled,
                ttl_seconds=policy.local_cache_ttl_seconds,
                affinity_ttl_seconds=policy.session_affinity_ttl_seconds,
                redis_url=settings.model_router_redis_url or None,
                shared_local_cache=policy.shared_local_cache_enabled,
            )
            _cache_policy_sig = sig
            return _default_cache
        if _cache_policy_sig != sig:
            _default_cache.configure(
                enabled=policy.prompt_cache_enabled,
                ttl_seconds=policy.local_cache_ttl_seconds,
                affinity_ttl_seconds=policy.session_affinity_ttl_seconds,
                redis_url=settings.model_router_redis_url or None,
                shared_local_cache=policy.shared_local_cache_enabled,
            )
            _cache_policy_sig = sig
        return _default_cache


def reset_prompt_cache_for_tests() -> None:
    """Test helper: clear entries and re-sync from current policy."""
    from model_router.redis_store import reset_redis_client_for_tests

    global _cache_policy_sig, _default_cache
    reset_redis_client_for_tests()
    with _cache_lock:
        if _default_cache is not None:
            _default_cache.clear()
        _default_cache = None
        _cache_policy_sig = None
    get_prompt_cache()
