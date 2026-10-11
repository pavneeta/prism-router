"""Redis affinity hooks, provider health, feedback API, latency bias."""

from __future__ import annotations

from fastapi.testclient import TestClient

from model_router.config import (
    BenchmarksConfig,
    Deployment,
    ModelBenchmark,
    ModelsConfig,
    PolicyConfig,
    clear_config_caches,
    get_settings,
)
from model_router.gateway import app
from model_router.policy import SelectionPolicy
from model_router.prompt_cache import PromptCacheLayer, reset_prompt_cache_for_tests
from model_router.provider_health import get_provider_health, reset_provider_health_for_tests


def test_provider_health_deprioritizes_failing_provider():
    reset_provider_health_for_tests()
    health = get_provider_health()
    for _ in range(8):
        health.record(litellm_model="openai/gpt-4o-mini", success=False)
    for _ in range(3):
        health.record(litellm_model="anthropic/claude-3-5-sonnet", success=True)

    policy_cfg = PolicyConfig(
        default_min_accuracy=0.0,
        provider_health_enabled=True,
        provider_health_penalty=5.0,
        latency_penalty_usd_per_ms=0.0,
    )
    benches = BenchmarksConfig(
        models={
            "cheap-openai": ModelBenchmark(
                input_cost_per_m=0.1,
                output_cost_per_m=0.1,
                accuracy={"general_chat": 0.9},
                p50_latency_ms=100,
            ),
            "cheap-anthropic": ModelBenchmark(
                input_cost_per_m=0.1,
                output_cost_per_m=0.1,
                accuracy={"general_chat": 0.9},
                p50_latency_ms=100,
            ),
        }
    )
    models = ModelsConfig(
        deployments=[
            Deployment(id="cheap-openai", litellm_model="openai/gpt-4o-mini"),
            Deployment(id="cheap-anthropic", litellm_model="anthropic/claude-3-5-sonnet"),
        ]
    )
    policy = SelectionPolicy(policy=policy_cfg, benchmarks=benches, models=models)
    decision = policy.select(
        task_type="general_chat",
        classification_confidence=0.95,
        prompt_text="hello",
        provider_health=health,
    )
    assert decision.selected_model == "cheap-anthropic"


def test_latency_penalty_prefers_faster_model():
    policy_cfg = PolicyConfig(
        default_min_accuracy=0.0,
        provider_health_enabled=False,
        latency_penalty_usd_per_ms=0.001,
    )
    benches = BenchmarksConfig(
        models={
            "slow": ModelBenchmark(
                input_cost_per_m=0.1,
                output_cost_per_m=0.1,
                accuracy={"general_chat": 0.9},
                p50_latency_ms=5000,
            ),
            "fast": ModelBenchmark(
                input_cost_per_m=0.1,
                output_cost_per_m=0.1,
                accuracy={"general_chat": 0.9},
                p50_latency_ms=50,
            ),
        }
    )
    models = ModelsConfig(
        deployments=[
            Deployment(id="slow", litellm_model="openai/slow"),
            Deployment(id="fast", litellm_model="openai/fast"),
        ]
    )
    policy = SelectionPolicy(policy=policy_cfg, benchmarks=benches, models=models)
    decision = policy.select(
        task_type="general_chat",
        classification_confidence=0.95,
        prompt_text="hello",
    )
    assert decision.selected_model == "fast"


def test_feedback_endpoint_appends_jsonl(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_ROUTER_DRY_RUN", "true")
    monkeypatch.setenv("MODEL_ROUTER_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))
    monkeypatch.setenv("MODEL_ROUTER_FEEDBACK_PATH", str(tmp_path / "feedback.jsonl"))
    get_settings.cache_clear()
    clear_config_caches()
    reset_prompt_cache_for_tests()
    reset_provider_health_for_tests()
    client = TestClient(app)
    resp = client.post(
        "/v1/router/feedback",
        json={"session_id": "sess-1", "outcome": "pass", "task_hint": "code_generation"},
    )
    assert resp.status_code == 200
    lines = (tmp_path / "feedback.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert "sess-1" in lines[0]


def test_prompt_cache_in_memory_backend_without_redis():
    reset_prompt_cache_for_tests()
    cache = PromptCacheLayer(enabled=True, redis_url=None)
    assert cache.backend() == "in_memory"
    cache.set_affinity("s1", model_id="m1", litellm_model="openai/m1", prefix_tokens_estimate=10)
    aff = cache.get_affinity("s1")
    assert aff is not None
    assert aff.model_id == "m1"
