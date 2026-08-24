"""Client API key gate for public gateway deploys."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from model_router.client_auth import client_api_key_ok, extract_client_api_key
from model_router.config import clear_config_caches, get_settings
from model_router.gateway import app
from model_router.prompt_cache import reset_prompt_cache_for_tests


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_ROUTER_DRY_RUN", "true")
    monkeypatch.setenv("MODEL_ROUTER_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))
    monkeypatch.setenv("MODEL_ROUTER_RATE_LIMIT_RPM", "0")
    monkeypatch.delenv("MODEL_ROUTER_API_KEYS", raising=False)
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


def test_extract_bearer_and_x_api_key():
    assert extract_client_api_key("Bearer secret-1", None) == "secret-1"
    assert extract_client_api_key(None, "secret-2") == "secret-2"
    assert extract_client_api_key("Bearer a", "b") == "b"
    assert extract_client_api_key("Basic x", None) is None


def test_compare_keys():
    allowed = frozenset({"alpha", "beta"})
    assert client_api_key_ok("alpha", allowed)
    assert not client_api_key_ok("gamma", allowed)
    assert client_api_key_ok(None, frozenset())


def test_open_when_no_keys_configured(client: TestClient):
    assert client.get("/health").status_code == 200
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200


def test_rejects_missing_key(monkeypatch, client: TestClient):
    monkeypatch.setenv("MODEL_ROUTER_API_KEYS", "test-key-one,test-key-two")
    get_settings.cache_clear()
    assert client.get("/health").status_code == 200
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_api_key"


def test_accepts_bearer_and_x_api_key(monkeypatch, client: TestClient):
    monkeypatch.setenv("MODEL_ROUTER_API_KEYS", "test-key-one,test-key-two")
    get_settings.cache_clear()
    r1 = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key-one"},
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r1.status_code == 200
    r2 = client.post(
        "/v1/chat/completions",
        headers={"X-Api-Key": "test-key-two"},
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r2.status_code == 200
