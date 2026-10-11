"""Production hardening: /ready, OpenAI errors, redaction, rate limit, telemetry soft-fail."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from model_router.config import clear_config_caches, get_settings
from model_router.gateway import app
from model_router.prompt_cache import reset_prompt_cache_for_tests
from model_router.rate_limit import InProcessRateLimiter
from model_router.safety import redact_secrets
from model_router.telemetry import TelemetryEvent, TelemetryLogger, now_ts


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_ROUTER_DRY_RUN", "true")
    monkeypatch.setenv("MODEL_ROUTER_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))
    monkeypatch.setenv("MODEL_ROUTER_RATE_LIMIT_RPM", "0")
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


def test_ready(client: TestClient):
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["config"]["policy"] is True
    assert body["config"]["benchmarks"] > 0
    assert body["session_store"] == "in_memory"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", body["benchmarks_snapshot_date"] or "")


def test_openai_error_shape_on_not_found(client: TestClient):
    resp = client.get("/v1/router/sessions/does-not-exist-xyz")
    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body
    assert body["error"]["type"] == "invalid_request_error"
    assert "detail" not in body


def test_redact_secrets():
    assert "[REDACTED]" in (redact_secrets("fail sk-abcdefghijklmnopqrstuvwxyz012345") or "")
    assert redact_secrets("plain error") == "plain error"


def test_rate_limiter_blocks():
    lim = InProcessRateLimiter(rpm=2)
    assert lim.allow("a")
    assert lim.allow("a")
    assert not lim.allow("a")
    assert lim.allow("b")


def test_telemetry_soft_fail_on_bad_path(tmp_path):
    # Parent is a file → mkdir/write must not raise
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    logger = TelemetryLogger(path=blocker / "telemetry.jsonl")
    logger.emit(
        TelemetryEvent(
            ts=now_ts(),
            request_id="r1",
            session_id=None,
            route_mode="auto",
            requested_model="auto",
            selected_model="x",
            litellm_model="x",
            task_type="general_chat",
            classification_confidence=1.0,
            classification_signals=[],
            policy_reason="test",
            estimated_cost_usd=0.0,
            frontier_cost_usd=0.0,
            cost_delta_vs_frontier_usd=0.0,
            error="leak sk-abcdefghijklmnopqrstuvwxyz012345",
        )
    )


def test_settings_production_defaults(monkeypatch):
    monkeypatch.delenv("MODEL_ROUTER_DRY_RUN", raising=False)
    monkeypatch.delenv("MODEL_ROUTER_MIRROR_MODE", raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert s.model_router_dry_run is False
    assert s.model_router_mirror_mode is False
    assert s.model_router_rate_limit_rpm == 0
