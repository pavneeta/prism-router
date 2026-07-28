from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any


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
    """Local exact-match cache + in-memory session affinity for provider prompt cache."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        ttl_seconds: float = 300.0,
        max_entries: int = 2048,
        affinity_ttl_seconds: float = 1800.0,
    ) -> None:
        self.enabled = enabled
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.affinity_ttl_seconds = affinity_ttl_seconds
        self._local: dict[str, LocalCacheEntry] = {}
        self._affinity: dict[str, SessionAffinity] = {}
        self._lock = threading.Lock()

    def configure(
        self,
        *,
        enabled: bool | None = None,
        ttl_seconds: float | None = None,
        affinity_ttl_seconds: float | None = None,
    ) -> None:
        """Apply policy.yaml knobs without dropping existing entries."""
        with self._lock:
            if enabled is not None:
                self.enabled = enabled
            if ttl_seconds is not None:
                self.ttl_seconds = ttl_seconds
            if affinity_ttl_seconds is not None:
                self.affinity_ttl_seconds = affinity_ttl_seconds

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

    def get_local(self, key: str) -> CacheLookupResult:
        if not self.enabled:
            return CacheLookupResult(hit=False, layer="none")
        now = time.time()
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
        with self._lock:
            if len(self._local) >= self.max_entries:
                # Drop oldest
                oldest = min(self._local.items(), key=lambda kv: kv[1].created_at)
                del self._local[oldest[0]]
            self._local[key] = LocalCacheEntry(response=response, created_at=time.time())

    def get_affinity(self, session_id: str | None) -> SessionAffinity | None:
        if not session_id:
            return None
        now = time.time()
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
        with self._lock:
            self._affinity[session_id] = SessionAffinity(
                model_id=model_id,
                litellm_model=litellm_model,
                prefix_tokens_estimate=prefix_tokens_estimate,
                updated_at=time.time(),
            )


_default_cache: PromptCacheLayer | None = None
_cache_policy_sig: tuple[bool, float, float] | None = None
_cache_lock = threading.Lock()


def get_prompt_cache() -> PromptCacheLayer:
    """Process-wide cache; TTLs / enabled flag come from policy.yaml."""
    from model_router.config import load_policy

    global _default_cache, _cache_policy_sig
    policy = load_policy()
    sig = (
        policy.prompt_cache_enabled,
        policy.local_cache_ttl_seconds,
        policy.session_affinity_ttl_seconds,
    )
    with _cache_lock:
        if _default_cache is None:
            _default_cache = PromptCacheLayer(
                enabled=policy.prompt_cache_enabled,
                ttl_seconds=policy.local_cache_ttl_seconds,
                affinity_ttl_seconds=policy.session_affinity_ttl_seconds,
            )
            _cache_policy_sig = sig
            return _default_cache
        if _cache_policy_sig != sig:
            _default_cache.configure(
                enabled=policy.prompt_cache_enabled,
                ttl_seconds=policy.local_cache_ttl_seconds,
                affinity_ttl_seconds=policy.session_affinity_ttl_seconds,
            )
            _cache_policy_sig = sig
        return _default_cache


def reset_prompt_cache_for_tests() -> None:
    """Test helper: clear entries and re-sync from current policy."""
    global _cache_policy_sig
    with _cache_lock:
        if _default_cache is not None:
            _default_cache.clear()
        _cache_policy_sig = None
    get_prompt_cache()
