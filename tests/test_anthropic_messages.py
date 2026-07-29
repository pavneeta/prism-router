from fastapi.testclient import TestClient

from model_router.config import clear_config_caches, get_settings
from model_router.gateway import app
from model_router.prompt_cache import reset_prompt_cache_for_tests


def test_anthropic_messages_dry_run(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_ROUTER_DRY_RUN", "true")
    monkeypatch.setenv("MODEL_ROUTER_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))
    get_settings.cache_clear()
    clear_config_caches()
    reset_prompt_cache_for_tests()
    client = TestClient(app)
    resp = client.post(
        "/v1/messages",
        json={
            "model": "auto",
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "Say hi"}],
        },
        headers={"X-Session-Id": "anthropic-test"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "message"
    assert data["role"] == "assistant"
    assert data["content"][0]["type"] == "text"
    assert "model_router" in data


def test_session_rollup_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_ROUTER_DRY_RUN", "true")
    monkeypatch.setenv("MODEL_ROUTER_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))
    get_settings.cache_clear()
    clear_config_caches()
    reset_prompt_cache_for_tests()
    client = TestClient(app)
    sid = "rollup-e2e"
    r1 = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 8,
        },
        headers={"X-Session-Id": sid},
    )
    assert r1.status_code == 200
    r2 = client.get(f"/v1/router/sessions/{sid}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["session_id"] == sid
    assert body["rollup"]["request_count"] >= 1
