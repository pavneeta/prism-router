from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from model_router.config import clear_config_caches, get_settings
from model_router.gateway import app
from model_router.mirror import (
    append_mirror_record,
    judge_pair,
    should_mirror,
    shadow_select,
)
from model_router.prompt_cache import reset_prompt_cache_for_tests
from model_router.classifier import Classification


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_ROUTER_DRY_RUN", "false")
    monkeypatch.setenv("MODEL_ROUTER_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))
    monkeypatch.setenv("MODEL_ROUTER_MIRROR_MODE", "true")
    monkeypatch.setenv("MODEL_ROUTER_MIRROR_PATH", str(tmp_path / "mirror.jsonl"))
    monkeypatch.setenv("MODEL_ROUTER_MIRROR_JUDGE", "false")
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


def test_should_mirror_gates():
    settings = get_settings()
    assert should_mirror(
        settings, requested_model="openai/gpt-4o-mini", route_mode="passthrough", stream=False
    )
    assert not should_mirror(
        settings, requested_model="auto", route_mode="auto", stream=False
    )
    assert not should_mirror(
        settings,
        requested_model="openai/gpt-4o-mini",
        route_mode="passthrough",
        stream=True,
    )


def test_shadow_select_returns_decision():
    cls = Classification(task_type="general_chat", confidence=0.9, signals=["test"])
    decision = shadow_select(
        classification=cls,
        prompt_text="Hello there",
        session_id=None,
        likely_prefix_reuse=False,
    )
    assert decision.selected_model
    assert decision.litellm_model


def test_append_mirror_record(tmp_path):
    path = tmp_path / "m.jsonl"
    append_mirror_record(path, {"request_id": "abc", "primary": {"content": "hi"}})
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["request_id"] == "abc"


@pytest.mark.asyncio
async def test_judge_pair_parses_json():
    mock_resp = MagicMock()
    mock_resp.model_dump.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"winner":"auto","score":0.8,"rationale":"clearer"}',
                }
            }
        ]
    }
    with patch("model_router.mirror.acompletion", new=AsyncMock(return_value=mock_resp)):
        out = await judge_pair(
            judge_model="openai/gpt-4o-mini",
            task_type="general_chat",
            user_prompt="hi",
            primary_content="hello",
            auto_content="Hello!",
            primary_model="openai/gpt-4o-mini",
            auto_model="openai/gpt-5.6-luna",
        )
    assert out["winner"] == "auto"
    assert out["score"] == 0.8


def test_mirror_passthrough_schedules_shadow(client, tmp_path):
    primary = MagicMock()
    primary.model_dump.return_value = {
        "id": "chatcmpl-primary",
        "object": "chat.completion",
        "model": "gpt-4o-mini",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "primary-out"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }
    primary.usage = MagicMock(prompt_tokens=3, completion_tokens=2, total_tokens=5)

    scheduled: list[dict] = []

    def _capture(**kwargs):
        scheduled.append(kwargs)

    with (
        patch("model_router.gateway.acompletion", new=AsyncMock(return_value=primary)),
        patch("model_router.gateway.completion_cost", return_value=0.0),
        patch("model_router.gateway.schedule_mirror_eval", side_effect=_capture),
    ):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "openai/gpt-4o-mini",
                "temperature": 0,
                "messages": [{"role": "user", "content": "Say hi"}],
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "primary-out"
    assert body["model_router"]["mirror"]["enabled"] is True
    assert len(scheduled) == 1
    assert scheduled[0]["requested_model"] == "openai/gpt-4o-mini"
    assert scheduled[0]["primary_content"] == "primary-out"


def test_mirror_skips_when_client_asks_auto(client, monkeypatch):
    monkeypatch.setenv("MODEL_ROUTER_DRY_RUN", "true")
    get_settings.cache_clear()
    with patch("model_router.gateway.schedule_mirror_eval") as sched:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "auto",
                "messages": [{"role": "user", "content": "Say hi"}],
            },
        )
    assert resp.status_code == 200
    assert "mirror" not in (resp.json().get("model_router") or {})
    sched.assert_not_called()


def test_health_exposes_mirror_flags(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mirror_mode"] is True
    assert body["mirror_judge"] is False
