from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    model_router_config_dir: str = "config"
    model_router_telemetry_path: str = "logs/telemetry.jsonl"
    model_router_host: str = "0.0.0.0"
    model_router_port: int = 4000
    # Production defaults: live routing, no shadow-eval double spend
    model_router_dry_run: bool = False
    # Shadow-eval: also run auto routing/completion alongside customer model
    model_router_mirror_mode: bool = False
    model_router_mirror_path: str = "logs/mirror.jsonl"
    model_router_mirror_judge: bool = False
    model_router_mirror_judge_model: str = "openai/gpt-4o-mini"
    # Comma-separated CORS origins; empty = no CORS middleware; "*" = allow all
    model_router_cors_origins: str = ""
    # In-process requests/minute per client IP; 0 = disabled (prefer Railway/edge limits)
    model_router_rate_limit_rpm: int = 0
    # Optional public URL of this gateway — also cleared from provider *_API_BASE envs
    model_router_public_base: str = ""
    # Comma-separated client API keys. Empty = no client auth (local default).
    # Set on any public deploy so the internet cannot spend your provider keys.
    model_router_api_keys: str = ""
    # Optional Redis URL for cross-replica session affinity (+ optional shared local cache)
    model_router_redis_url: str = ""
    model_router_feedback_path: str = "logs/feedback.jsonl"

    @property
    def config_dir(self) -> Path:
        return Path(self.model_router_config_dir)

    def cors_origin_list(self) -> list[str]:
        raw = (self.model_router_cors_origins or "").strip()
        if not raw:
            return []
        if raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


class PolicyConfig(BaseModel):
    default_min_accuracy: float = 0.75
    min_accuracy_by_task: dict[str, float] = Field(default_factory=dict)
    frontier_model: str = "openai/gpt-4o"
    auto_model_ids: list[str] = Field(default_factory=lambda: ["model-router/auto", "auto"])
    safe_fallback_model: str = "openai/gpt-4o-mini"
    default_estimated_output_tokens: int = 512
    min_classification_confidence: float = 0.35
    # Cache-aware routing
    prompt_cache_enabled: bool = True
    local_cache_ttl_seconds: float = 300.0
    session_affinity_ttl_seconds: float = 1800.0
    # Prefer sticky model unless another is cheaper by this relative margin after cold pricing
    cache_switch_savings_margin: float = 0.15
    # Assumed fraction of prompt tokens reusable via provider cache on sticky turns
    default_cache_hit_ratio: float = 0.7
    # Prefer caching-capable models when estimated prefix is at least this many tokens
    prefer_caching_models_above_prefix_tokens: int = 1024
    # Fireworks reasoning models: disable visible thinking / CoT in content
    fireworks_hide_thinking: bool = True
    # Soft latency bias: add (usd_per_ms * p50_latency_ms) to effective cost when > 0
    latency_penalty_usd_per_ms: float = 0.0
    # Multiply estimated cost by (1 + provider_health_penalty * ewma_error_rate)
    provider_health_penalty: float = 1.5
    provider_health_enabled: bool = True
    # When Redis is configured, mirror local exact-match cache entries across replicas
    shared_local_cache_enabled: bool = False
    # Widen sticky margin when session shows high affinity preserve ratio (0 = off)
    observed_sticky_margin_boost: float = 0.1

    def min_accuracy(self, task_type: str) -> float:
        return self.min_accuracy_by_task.get(task_type, self.default_min_accuracy)


class ModelBenchmark(BaseModel):
    context_window: int = 128000
    input_cost_per_m: float
    output_cost_per_m: float
    cached_input_cost_per_m: float | None = None
    supports_prompt_caching: bool = False
    p50_latency_ms: float | None = None
    # Raw public leaderboard metrics — see docs/BENCHMARKS.md
    sources: dict[str, Any] = Field(default_factory=dict)
    # Task accuracies in [0,1]. If empty/partial, derived from sources on load.
    accuracy: dict[str, float] = Field(default_factory=dict)
    notes: str | None = None

    def cached_input_rate(self) -> float:
        if self.cached_input_cost_per_m is not None:
            return self.cached_input_cost_per_m
        if self.supports_prompt_caching:
            return self.input_cost_per_m * 0.5
        return self.input_cost_per_m


class BenchmarksConfig(BaseModel):
    schema_version: int = 1
    snapshot_date: str | None = None
    sources_docs: str | None = None
    models: dict[str, ModelBenchmark]


class Deployment(BaseModel):
    id: str
    litellm_model: str
    enabled: bool = True


class ModelsConfig(BaseModel):
    deployments: list[Deployment]


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


@lru_cache
def get_settings() -> Settings:
    return Settings()


# mtime-based YAML load cache (invalidates when files change on disk)
_yaml_cache: dict[str, tuple[float, Any]] = {}
_yaml_lock = threading.Lock()


def _cached_yaml_load(path: Path, builder: Any) -> Any:
    key = str(path.resolve())
    mtime = path.stat().st_mtime
    with _yaml_lock:
        hit = _yaml_cache.get(key)
        if hit is not None and hit[0] == mtime:
            return hit[1]
    value = builder()
    with _yaml_lock:
        _yaml_cache[key] = (mtime, value)
    return value


def clear_config_caches() -> None:
    """Test helper: drop mtime caches and selection-policy singleton."""
    with _yaml_lock:
        _yaml_cache.clear()
    clear_selection_policy()


def load_policy(config_dir: Path | None = None) -> PolicyConfig:
    path = (config_dir or get_settings().config_dir) / "policy.yaml"

    def _build() -> PolicyConfig:
        return PolicyConfig.model_validate(_load_yaml(path))

    return _cached_yaml_load(path, _build)


def load_benchmarks(config_dir: Path | None = None) -> BenchmarksConfig:
    from model_router.benchmarks import materialize_accuracy

    path = (config_dir or get_settings().config_dir) / "benchmarks.yaml"

    def _build() -> BenchmarksConfig:
        cfg = BenchmarksConfig.model_validate(_load_yaml(path))
        cfg.models = {mid: materialize_accuracy(bench) for mid, bench in cfg.models.items()}
        return cfg

    return _cached_yaml_load(path, _build)


def load_models(config_dir: Path | None = None) -> ModelsConfig:
    path = (config_dir or get_settings().config_dir) / "models.yaml"

    def _build() -> ModelsConfig:
        return ModelsConfig.model_validate(_load_yaml(path))

    return _cached_yaml_load(path, _build)


# Single SelectionPolicy keyed by config mtimes
_selection_policy: Any | None = None
_selection_policy_sig: tuple[float, float, float] | None = None
_selection_lock = threading.Lock()


def _config_mtimes(config_dir: Path | None = None) -> tuple[float, float, float]:
    base = config_dir or get_settings().config_dir
    return (
        (base / "policy.yaml").stat().st_mtime,
        (base / "benchmarks.yaml").stat().st_mtime,
        (base / "models.yaml").stat().st_mtime,
    )


def get_selection_policy(config_dir: Path | None = None) -> Any:
    """Return a process-wide SelectionPolicy, rebuilt when YAML mtimes change."""
    from model_router.policy import SelectionPolicy

    global _selection_policy, _selection_policy_sig
    sig = _config_mtimes(config_dir)
    with _selection_lock:
        if _selection_policy is not None and _selection_policy_sig == sig:
            return _selection_policy
        policy = SelectionPolicy(
            policy=load_policy(config_dir),
            benchmarks=load_benchmarks(config_dir),
            models=load_models(config_dir),
        )
        _selection_policy = policy
        _selection_policy_sig = sig
        return policy


def clear_selection_policy() -> None:
    global _selection_policy, _selection_policy_sig
    with _selection_lock:
        _selection_policy = None
        _selection_policy_sig = None
