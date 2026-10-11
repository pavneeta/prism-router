"""Unit + integration tests for in-process usage metrics."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from model_router.config import clear_config_caches, get_settings
from model_router.gateway import app
from model_router.litellm_backend import extract_token_usage, provider_type
from model_router.prompt_cache import reset_prompt_cache_for_tests
from model_router.usage_metrics import (
    UsageMetricsStore,
    get_usage_metrics,
    reset_usage_metrics_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_ROUTER_DRY_RUN", "true")
    monkeypatch.setenv("MODEL_ROUTER_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))
    get_settings.cache_clear()
    clear_config_caches()
    reset_prompt_cache_for_tests()
    reset_usage_metrics_for_tests()
    yield
    get_settings.cache_clear()
    clear_config_caches()
    reset_prompt_cache_for_tests()
    reset_usage_metrics_for_tests()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_provider_type_families():
    assert provider_type("openai/gpt-4o-mini") == "openai"
    assert provider_type("anthropic/claude-sonnet-4-5") == "anthropic"
    assert provider_type("fireworks_ai/accounts/fireworks/models/kimi") == "fireworks"
    assert provider_type("claude-3-5-sonnet") == "anthropic"
    assert provider_type("mystery-model") == "unknown"


def test_extract_token_usage_openai_cached():
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "prompt_tokens_details": {"cached_tokens": 40},
    }
    assert extract_token_usage(usage) == (100, 20, 40)


def test_extract_token_usage_anthropic_cache_read():
    usage = {
        "prompt_tokens": 80,
        "completion_tokens": 10,
        "cache_read_input_tokens": 50,
    }
    assert extract_token_usage(usage) == (80, 10, 50)


def test_usage_metrics_store_rollups_and_filters():
    store = UsageMetricsStore()
    store.record(
        session_id="s1",
        model="cheap-model",
        provider="openai",
        prompt_tokens=10,
        completion_tokens=5,
        cached_tokens=2,
        est_cost_usd=0.01,
        actual_cost_usd=0.009,
    )
    store.record(
        session_id="s1",
        model="frontier",
        provider="anthropic",
        prompt_tokens=100,
        completion_tokens=50,
        cached_tokens=0,
        est_cost_usd=0.2,
        actual_cost_usd=0.18,
    )
    store.record(
        session_id="s2",
        model="cheap-model",
        provider="openai",
        prompt_tokens=7,
        completion_tokens=3,
        cached_tokens=1,
        est_cost_usd=0.005,
        actual_cost_usd=None,
    )

    full = store.snapshot()
    assert full["scope"] == "in_process"
    assert "replica" in full["note"].lower() or "replicas" in full["note"].lower()
    assert full["totals"]["request_count"] == 3
    assert full["totals"]["prompt_tokens"] == 117
    assert full["totals"]["completion_tokens"] == 58
    assert full["totals"]["total_tokens"] == 175
    assert full["totals"]["cached_tokens"] == 3
    assert set(full["by_session"]) == {"s1", "s2"}
    assert set(full["by_model"]) == {"cheap-model", "frontier"}
    assert set(full["by_provider"]) == {"openai", "anthropic"}

    by_session = store.snapshot(session_id="s1")
    assert by_session["totals"]["request_count"] == 2
    assert by_session["totals"]["prompt_tokens"] == 110
    assert set(by_session["by_model"]) == {"cheap-model", "frontier"}

    by_model = store.snapshot(model="cheap-model")
    assert by_model["totals"]["request_count"] == 2
    assert by_model["totals"]["prompt_tokens"] == 17
    assert set(by_model["by_session"]) == {"s1", "s2"}
    assert set(by_model["by_provider"]) == {"openai"}

    by_provider = store.snapshot(provider="anthropic")
    assert by_provider["totals"]["request_count"] == 1
    assert by_provider["totals"]["completion_tokens"] == 50

    combo = store.snapshot(session_id="s1", model="cheap-model", provider="openai")
    assert combo["totals"]["request_count"] == 1
    assert combo["totals"]["cached_tokens"] == 2


def test_usage_metrics_endpoint_empty(client: TestClient):
    resp = client.get("/v1/router/metrics/usage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "in_process"
    assert body["totals"]["request_count"] == 0
    assert body["by_session"] == {}
    assert body["by_model"] == {}
    assert body["by_provider"] == {}
    assert "note" in body


def test_usage_metrics_endpoint_after_dry_run(client: TestClient):
    sid = "metrics-dry-run-1"
    r1 = client.post(
        "/v1/chat/completions",
        headers={"X-Session-Id": sid},
        json={
            "model": "model-router/auto",
            "temperature": 0,
            "messages": [{"role": "user", "content": "Hello metrics"}],
        },
    )
    assert r1.status_code == 200
    selected = r1.json()["model_router"]["decision"]["selected_model"]

    resp = client.get("/v1/router/metrics/usage", params={"session_id": sid})
    assert resp.status_code == 200
    body = resp.json()
    assert body["filters"]["session_id"] == sid
    assert body["totals"]["request_count"] >= 1
    assert sid in body["by_session"]
    assert selected in body["by_model"]
    assert body["by_provider"]  # at least one provider key
    # Dry-run has zero usage tokens
    assert body["totals"]["prompt_tokens"] == 0


@pytest.mark.asyncio
async def test_usage_metrics_from_mocked_completion(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_ROUTER_DRY_RUN", "false")
    monkeypatch.setenv("MODEL_ROUTER_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))
    get_settings.cache_clear()
    clear_config_caches()
    reset_prompt_cache_for_tests()
    reset_usage_metrics_for_tests()

    usage = MagicMock()
    usage.prompt_tokens = 42
    usage.completion_tokens = 7
    usage.total_tokens = 49
    usage.prompt_tokens_details = MagicMock()
    usage.prompt_tokens_details.cached_tokens = 12
    usage.model_dump = lambda: {
        "prompt_tokens": 42,
        "completion_tokens": 7,
        "total_tokens": 49,
        "prompt_tokens_details": {"cached_tokens": 12},
    }

    response = MagicMock()
    response.usage = usage
    response.model_dump = lambda: {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "model": "openai/gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hi"},
                "finish_reason": "stop",
            }
        ],
        "usage": usage.model_dump(),
    }

    mock_acompletion = AsyncMock(return_value=response)

    with patch("model_router.gateway.acompletion", mock_acompletion):
        with patch("model_router.gateway.completion_cost", return_value=0.0012):
            with TestClient(app) as client:
                sid = "metrics-live-mock"
                resp = client.post(
                    "/v1/chat/completions",
                    headers={"X-Session-Id": sid},
                    json={
                        "model": "openai/gpt-4o-mini",
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )
                assert resp.status_code == 200

                metrics = client.get(
                    "/v1/router/metrics/usage",
                    params={"session_id": sid},
                ).json()
                assert metrics["totals"]["request_count"] == 1
                assert metrics["totals"]["prompt_tokens"] == 42
                assert metrics["totals"]["completion_tokens"] == 7
                assert metrics["totals"]["total_tokens"] == 49
                assert metrics["totals"]["cached_tokens"] == 12
                assert metrics["totals"]["actual_cost_usd"] == pytest.approx(0.0012)
                assert "openai" in metrics["by_provider"]
                assert metrics["by_provider"]["openai"]["prompt_tokens"] == 42


@pytest.mark.asyncio
async def test_streaming_records_usage_from_final_chunk(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_ROUTER_DRY_RUN", "false")
    monkeypatch.setenv("MODEL_ROUTER_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))
    get_settings.cache_clear()
    clear_config_caches()
    reset_prompt_cache_for_tests()
    reset_usage_metrics_for_tests()

    class FakeChunk:
        def __init__(self, content: str = "", finish: str | None = None, usage: dict | None = None):
            self._content = content
            self._finish = finish
            self._usage = usage

        def model_dump(self) -> dict[str, Any]:
            data: dict[str, Any] = {
                "id": "chatcmpl-mock",
                "object": "chat.completion.chunk",
                "model": "openai/gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": self._content} if self._content else {},
                        "finish_reason": self._finish,
                    }
                ],
            }
            if self._usage is not None:
                data["usage"] = self._usage
            return data

    async def fake_stream():
        yield FakeChunk("Hello")
        yield FakeChunk("", finish="stop", usage={
            "prompt_tokens": 15,
            "completion_tokens": 3,
            "total_tokens": 18,
            "prompt_tokens_details": {"cached_tokens": 4},
        })

    mock_acompletion = AsyncMock(return_value=fake_stream())

    with patch("model_router.gateway.acompletion", mock_acompletion):
        with TestClient(app) as client:
            sid = "metrics-stream-mock"
            resp = client.post(
                "/v1/chat/completions",
                headers={"X-Session-Id": sid},
                json={
                    "model": "openai/gpt-4o-mini",
                    "stream": True,
                    "messages": [{"role": "user", "content": "Say hi"}],
                },
            )
            assert resp.status_code == 200
            assert "[DONE]" in resp.text

            metrics = get_usage_metrics().snapshot(session_id=f"anonymous:{sid}")
            assert metrics["totals"]["request_count"] == 1
            assert metrics["totals"]["prompt_tokens"] == 15
            assert metrics["totals"]["completion_tokens"] == 3
            assert metrics["totals"]["cached_tokens"] == 4
            # OpenAI-family streaming should request include_usage
            assert mock_acompletion.await_args.kwargs.get("stream_options") == {
                "include_usage": True
            }
