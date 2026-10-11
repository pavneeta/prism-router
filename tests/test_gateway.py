from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from model_router.config import clear_config_caches, get_settings
from model_router.gateway import app
from model_router.prompt_cache import get_prompt_cache, reset_prompt_cache_for_tests


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_ROUTER_DRY_RUN", "true")
    monkeypatch.setenv("MODEL_ROUTER_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))
    get_settings.cache_clear()
    clear_config_caches()
    reset_prompt_cache_for_tests()
    yield
    get_settings.cache_clear()
    clear_config_caches()
    reset_prompt_cache_for_tests()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "dry_run" in body
    assert "providers" in body


def test_dry_run_chat_completions(client: TestClient):
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "model-router/auto",
            "temperature": 0,
            "messages": [{"role": "user", "content": "Hello — keep it short."}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert "[dry-run]" in data["choices"][0]["message"]["content"]
    assert data["model_router"]["classification"]["task_type"] == "general_chat"
    assert data["model_router"]["decision"] is not None
    assert data["model_router"]["cache"]["hit"] is False


def test_local_response_cache_disabled_by_default(client: TestClient):
    body = {
        "model": "model-router/auto",
        "temperature": 0,
        "messages": [{"role": "user", "content": "Cache me please."}],
    }
    first = client.post("/v1/chat/completions", json=body)
    assert first.status_code == 200
    assert first.json()["model_router"]["cache"]["hit"] is False

    second = client.post("/v1/chat/completions", json=body)
    assert second.status_code == 200
    data = second.json()
    assert data["model_router"]["cache"]["hit"] is False


def test_session_affinity_header(client: TestClient):
    headers = {"X-Session-Id": "agent-session-test-1"}
    body = {
        "model": "model-router/auto",
        "temperature": 0,
        "messages": [
            {"role": "user", "content": "Write a Python function that merges two sorted lists."}
        ],
    }
    first = client.post("/v1/chat/completions", headers=headers, json=body)
    assert first.status_code == 200
    selected = first.json()["model_router"]["decision"]["selected_model"]

    affinity = get_prompt_cache().get_affinity("anonymous:agent-session-test-1")
    assert affinity is not None
    assert affinity.model_id == selected

    # Follow-up with same session should stick
    follow = {
        "model": "model-router/auto",
        "temperature": 0,
        "messages": [
            {"role": "user", "content": "Write a Python function that merges two sorted lists."},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "Now add type hints."},
        ],
    }
    second = client.post("/v1/chat/completions", headers=headers, json=follow)
    assert second.status_code == 200
    assert second.json()["model_router"]["decision"]["selected_model"] == selected
    assert second.json()["model_router"]["decision"]["reason"] == (
        "session_affinity_preserve_prompt_cache"
    )


def test_opencode_stream_options_accepted(client: TestClient):
    """OpenCode sends stream_options.include_usage; extra=forbid used to 422."""
    resp = client.post(
        "/v1/chat/completions",
        headers={"X-Session-Id": "opencode-local"},
        json={
            "model": "model-router/auto",
            "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "user", "content": "Reply with exactly: opencode-smoke-ok"}],
        },
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    assert "data: " in resp.text


def test_streaming_dry_run_sse(client: TestClient):
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "model-router/auto",
            "stream": True,
            "messages": [{"role": "user", "content": "Hello stream"}],
        },
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    text = resp.text
    assert "data: " in text
    assert "[DONE]" in text
    assert "[dry-run]" in text or "chat.completion.chunk" in text


@pytest.mark.asyncio
async def test_streaming_mocked_litellm(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_ROUTER_DRY_RUN", "false")
    monkeypatch.setenv("TOGETHER_API_KEY", "test-only")
    monkeypatch.setenv("MODEL_ROUTER_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))
    get_settings.cache_clear()
    clear_config_caches()
    reset_prompt_cache_for_tests()

    class FakeChunk:
        def __init__(self, content: str, finish: str | None = None):
            self._content = content
            self._finish = finish

        def model_dump(self) -> dict[str, Any]:
            return {
                "id": "chatcmpl-mock",
                "object": "chat.completion.chunk",
                "model": "mock-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": self._content} if self._content else {},
                        "finish_reason": self._finish,
                    }
                ],
            }

    async def fake_stream():
        yield FakeChunk("Hello")
        yield FakeChunk(" world", finish="stop")

    mock_acompletion = AsyncMock(return_value=fake_stream())

    with patch("model_router.gateway.acompletion", mock_acompletion):
        with TestClient(app) as client:
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "model-router/auto",
                    "stream": True,
                    "messages": [{"role": "user", "content": "Say hi"}],
                },
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            lines = [ln for ln in resp.text.splitlines() if ln.startswith("data: ")]
            assert len(lines) >= 2
            assert lines[-1] == "data: [DONE]"
            first = json.loads(lines[0].removeprefix("data: "))
            assert first["choices"][0]["delta"]["content"] == "Hello"
            mock_acompletion.assert_awaited()
            assert mock_acompletion.await_args.kwargs.get("stream") is True
