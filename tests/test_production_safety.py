from __future__ import annotations

from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from model_router.config import (
    BenchmarksConfig,
    Deployment,
    ModelBenchmark,
    ModelsConfig,
    PolicyConfig,
    clear_config_caches,
    get_settings,
    validate_config_bundle,
)
from model_router.gateway import (
    ChatCompletionRequest,
    ChatMessage,
    _completion_kwargs,
    _deterministic_request,
    _local_cache_key,
    app,
    ready,
)
from model_router.policy import SelectionPolicy
from model_router.prompt_cache import reset_prompt_cache_for_tests


PROVIDER_ENV = {
    "openai": ("OPENAI_API_KEY", "openai/test"),
    "anthropic": ("ANTHROPIC_API_KEY", "anthropic/test"),
    "fireworks": ("FIREWORKS_API_KEY", "fireworks_ai/test"),
    "together": ("TOGETHER_API_KEY", "together_ai/test"),
}


@pytest.fixture(autouse=True)
def reset_global_config_after_test():
    yield
    get_settings.cache_clear()
    clear_config_caches()
    reset_prompt_cache_for_tests()


@pytest.mark.parametrize("provider", list(PROVIDER_ENV))
def test_credential_aware_policy_each_provider(monkeypatch, provider: str):
    for env_name, _ in PROVIDER_ENV.values():
        monkeypatch.delenv(env_name, raising=False)
    env_name, litellm_model = PROVIDER_ENV[provider]
    monkeypatch.setenv(env_name, "test-only")
    policy = PolicyConfig(
        default_min_accuracy=0,
        safe_fallback_model="only",
        frontier_model="only",
    )
    benchmarks = BenchmarksConfig(
        models={
            "only": ModelBenchmark(
                input_cost_per_m=1,
                output_cost_per_m=1,
                accuracy={"general_chat": 1},
            )
        }
    )
    models = ModelsConfig(
        deployments=[Deployment(id="only", litellm_model=litellm_model)]
    )
    decision = SelectionPolicy(
        policy=policy,
        benchmarks=benchmarks,
        models=models,
        require_credentials=True,
    ).select(
        task_type="general_chat",
        classification_confidence=1,
        prompt_text="hello",
    )
    assert decision.selected_model == "only"


def test_credential_aware_policy_fails_without_keys(monkeypatch):
    for env_name, _ in PROVIDER_ENV.values():
        monkeypatch.delenv(env_name, raising=False)
    policy = PolicyConfig(
        default_min_accuracy=0,
        safe_fallback_model="only",
        frontier_model="only",
    )
    benchmarks = BenchmarksConfig(
        models={
            "only": ModelBenchmark(
                input_cost_per_m=1,
                output_cost_per_m=1,
                accuracy={"general_chat": 1},
            )
        }
    )
    models = ModelsConfig(
        deployments=[Deployment(id="only", litellm_model="openai/test")]
    )
    with pytest.raises(RuntimeError, match="no viable auto deployments"):
        SelectionPolicy(
            policy=policy,
            benchmarks=benchmarks,
            models=models,
            require_credentials=True,
        ).select(
            task_type="general_chat",
            classification_confidence=1,
            prompt_text="hello",
        )


def test_low_confidence_requires_fallback_credential(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    policy = SelectionPolicy(
        policy=PolicyConfig(
            safe_fallback_model="fallback",
            frontier_model="fallback",
        ),
        benchmarks=BenchmarksConfig(
            models={
                "fallback": ModelBenchmark(
                    input_cost_per_m=1,
                    output_cost_per_m=1,
                    accuracy={"general_chat": 1},
                )
            }
        ),
        models=ModelsConfig(
            deployments=[Deployment(id="fallback", litellm_model="openai/test")]
        ),
        require_credentials=True,
    )
    with pytest.raises(RuntimeError, match="safe fallback"):
        policy.select(
            task_type="general_chat",
            classification_confidence=0,
            prompt_text="hello",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", list(PROVIDER_ENV))
async def test_ready_with_each_provider_independently(monkeypatch, provider: str):
    for env_name, _ in PROVIDER_ENV.values():
        monkeypatch.delenv(env_name, raising=False)
    env_name, litellm_model = PROVIDER_ENV[provider]
    monkeypatch.setenv(env_name, "test-only")
    policy = PolicyConfig(
        default_min_accuracy=0,
        safe_fallback_model="only",
        frontier_model="only",
    )
    benchmarks = BenchmarksConfig(
        models={
            "only": ModelBenchmark(
                input_cost_per_m=1,
                output_cost_per_m=1,
                accuracy={"general_chat": 1},
            )
        }
    )
    models = ModelsConfig(
        deployments=[Deployment(id="only", litellm_model=litellm_model)]
    )
    settings = SimpleNamespace(
        model_router_dry_run=False,
        model_router_mirror_mode=False,
        model_router_public_mode=False,
        model_router_api_keys="",
    )
    cache = SimpleNamespace(backend=lambda: "in_memory")
    with (
        patch("model_router.gateway.load_policy", return_value=policy),
        patch("model_router.gateway.load_benchmarks", return_value=benchmarks),
        patch("model_router.gateway.load_models", return_value=models),
        patch("model_router.gateway.get_settings", return_value=settings),
        patch("model_router.gateway.get_prompt_cache", return_value=cache),
    ):
        response = await ready()
    assert response.status_code == 200, response.body


@pytest.mark.asyncio
async def test_ready_rejects_no_credentials_and_missing_fallback(monkeypatch):
    for env_name, _ in PROVIDER_ENV.values():
        monkeypatch.delenv(env_name, raising=False)
    policy = PolicyConfig(
        default_min_accuracy=0,
        safe_fallback_model="fallback",
        frontier_model="fallback",
    )
    benchmarks = BenchmarksConfig(
        models={
            name: ModelBenchmark(
                input_cost_per_m=1,
                output_cost_per_m=1,
                accuracy={"general_chat": 1},
            )
            for name in ("candidate", "fallback")
        }
    )
    models = ModelsConfig(
        deployments=[
            Deployment(id="candidate", litellm_model="together_ai/test"),
            Deployment(id="fallback", litellm_model="openai/test"),
        ]
    )
    settings = SimpleNamespace(
        model_router_dry_run=False,
        model_router_mirror_mode=False,
        model_router_public_mode=False,
        model_router_api_keys="",
    )
    patches = (
        patch("model_router.gateway.load_policy", return_value=policy),
        patch("model_router.gateway.load_benchmarks", return_value=benchmarks),
        patch("model_router.gateway.load_models", return_value=models),
        patch("model_router.gateway.get_settings", return_value=settings),
    )
    with patches[0], patches[1], patches[2], patches[3]:
        no_keys = await ready()
    assert no_keys.status_code == 503
    assert b"no viable auto deployment" in no_keys.body

    monkeypatch.setenv("TOGETHER_API_KEY", "test-only")
    with patches[0], patches[1], patches[2], patches[3]:
        missing_fallback = await ready()
    assert missing_fallback.status_code == 503
    assert b"safe fallback provider credential unavailable" in missing_fallback.body


def test_cache_key_isolated_by_principal_and_all_fields():
    body = ChatCompletionRequest(
        model="auto",
        messages=[ChatMessage(role="user", content="hi")],
        temperature=0,
        top_p=0.5,
        stop=["END"],
        response_format={"type": "json_object"},
        seed=7,
        user="u1",
    )
    assert _local_cache_key(body, principal="key-a") != _local_cache_key(
        body, principal="key-b"
    )
    changed = body.model_copy(update={"user": "u2"})
    assert _local_cache_key(body, principal="key-a") != _local_cache_key(
        changed, principal="key-a"
    )


def test_cache_only_explicit_deterministic_requests():
    assert not _deterministic_request(
        ChatCompletionRequest(model="auto", messages=[], temperature=None)
    )
    assert not _deterministic_request(
        ChatCompletionRequest(
            model="auto",
            messages=[],
            temperature=0,
            tools=[{"type": "function", "function": {"name": "x"}}],
        )
    )
    assert not _deterministic_request(
        ChatCompletionRequest(
            model="auto",
            messages=[],
            temperature=0,
            tool_choice="auto",
        )
    )
    assert _deterministic_request(
        ChatCompletionRequest(model="auto", messages=[], temperature=0)
    )


def test_openai_fields_preserved():
    message = ChatMessage(
        role="assistant",
        content=None,
        name="agent",
        tool_calls=[{"id": "call-1", "type": "function"}],
        tool_call_id="call-0",
    )
    assert message.model_dump()["tool_calls"][0]["id"] == "call-1"
    body = ChatCompletionRequest(
        model="openai/test",
        messages=[message],
        top_p=0.8,
        stop=["stop"],
        response_format={"type": "json_object"},
        seed=42,
        parallel_tool_calls=False,
        reasoning_effort="low",
        max_completion_tokens=99,
    )
    kwargs = _completion_kwargs(body)
    assert kwargs == {
        "max_completion_tokens": 99,
        "top_p": 0.8,
        "stop": ["stop"],
        "response_format": {"type": "json_object"},
        "seed": 42,
        "parallel_tool_calls": False,
        "reasoning_effort": "low",
    }


def test_config_validation_duplicate_and_missing_benchmark():
    with pytest.raises(ValidationError, match="duplicate deployment"):
        ModelsConfig(
            deployments=[
                Deployment(id="x", litellm_model="openai/a"),
                Deployment(id="x", litellm_model="openai/b"),
            ]
        )
    errors = validate_config_bundle(
        policy=PolicyConfig(safe_fallback_model="x", frontier_model="x"),
        benchmarks=BenchmarksConfig(
            models={
                "x": ModelBenchmark(input_cost_per_m=1, output_cost_per_m=1)
            }
        ),
        models=ModelsConfig(
            deployments=[
                Deployment(id="x", litellm_model="openai/x"),
                Deployment(id="missing", litellm_model="openai/missing"),
            ]
        ),
    )
    assert any("missing" in err and "benchmark" in err for err in errors)


@pytest.mark.asyncio
async def test_nonstream_retry_once_on_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_ROUTER_DRY_RUN", "false")
    monkeypatch.setenv("MODEL_ROUTER_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))
    get_settings.cache_clear()
    clear_config_caches()
    reset_prompt_cache_for_tests()

    class FakeResponse:
        usage = None

        def model_dump(self):
            return {
                "id": "ok",
                "object": "chat.completion",
                "model": "openai/gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
            }

    mock = AsyncMock(side_effect=[TimeoutError("timeout"), FakeResponse()])
    with patch("model_router.gateway.acompletion", mock):
        with TestClient(app) as client:
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "openai/gpt-4o-mini",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
    assert response.status_code == 200
    assert mock.await_count == 2
