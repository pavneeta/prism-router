from __future__ import annotations

from model_router.cli import main as cli_main
from model_router.ui import (
    StatusReport,
    bool_providers,
    build_parser,
    collect_status,
    format_send,
    format_setup,
    format_status,
    normalize_base,
    provider_key_flags,
    send_prompt,
    start_gateway,
)


def test_parser_status_and_why_flags():
    status = build_parser().parse_args(["--status"])
    assert status.status is True
    assert status.why is None
    assert status.start is False

    why = build_parser().parse_args(["--why", "hello there"])
    assert why.why == "hello there"
    assert why.status is False

    send = build_parser().parse_args(["--send", "ping", "--base", "http://127.0.0.1:4001"])
    assert send.send == "ping"
    assert send.base == "http://127.0.0.1:4001"


def test_normalize_base_strips_v1_and_wildcard_bind():
    assert normalize_base("http://0.0.0.0:4000/v1") == "http://127.0.0.1:4000"
    assert normalize_base("127.0.0.1:4010") == "http://127.0.0.1:4010"


def test_format_status_gateway_down():
    text = format_status(
        StatusReport(
            gateway_up=False,
            dry_run=True,
            providers={"openai": False, "anthropic": True, "fireworks": False, "together": False},
            snapshot_date="2026-10-01",
            listen_url="http://127.0.0.1:4000",
            ready_status=None,
            start_hint="Gateway is not running. Start it in another terminal:\n\n  model-router\n",
        )
    )
    assert "gateway:    down" in text
    assert "dry_run:    true" in text
    assert "snapshot:   2026-10-01" in text
    assert "openai=false" in text
    assert "anthropic=true" in text
    assert "model-router" in text
    assert "sk-" not in text


def test_format_status_gateway_up():
    text = format_status(
        StatusReport(
            gateway_up=True,
            dry_run=False,
            providers={"openai": True, "anthropic": False, "fireworks": False, "together": False},
            snapshot_date="2026-10-01",
            listen_url="http://127.0.0.1:4000",
            ready_status="ready",
            start_hint=None,
        )
    )
    assert "gateway:    up" in text
    assert "ready:      ready" in text
    assert "openai=true" in text
    assert "Start it in another terminal" not in text


def test_collect_status_uses_mocked_health(monkeypatch):
    def fake_fetch(url: str, timeout: float = 0.6):
        if url.endswith("/health"):
            return 200, {
                "status": "ok",
                "dry_run": True,
                "providers": {
                    "openai": True,
                    "anthropic": False,
                    "fireworks": False,
                    "together": False,
                },
            }
        if url.endswith("/ready"):
            return 200, {"status": "ready"}
        return None

    report = collect_status(base="http://127.0.0.1:4000", fetch=fake_fetch)
    assert report.gateway_up is True
    assert report.dry_run is True
    assert report.providers["openai"] is True
    assert report.providers["anthropic"] is False
    assert report.ready_status == "ready"
    assert report.start_hint is None
    text = format_status(report)
    assert "gateway:    up" in text
    assert "true" in text
    assert not any(token.startswith("sk-") for token in text.split())


def test_collect_status_down_when_health_missing():
    report = collect_status(base="http://127.0.0.1:4000", fetch=lambda url, timeout=0.6: None)
    assert report.gateway_up is False
    assert report.start_hint is not None
    assert "model-router" in report.start_hint
    assert format_status(report).count("down") == 1


def test_provider_key_flags_are_bools_only(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-should-not-leak")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    flags = provider_key_flags()
    assert flags["openai"] is True
    assert flags["anthropic"] is False
    assert "sk-secret-should-not-leak" not in str(flags)
    assert bool_providers({"openai": "sk-secret"}) == {"openai": True}


def test_format_setup_is_local_only():
    text = format_setup("http://127.0.0.1:4000")
    assert 'OPENAI_API_BASE="http://127.0.0.1:4000/v1"' in text
    assert "model-router init opencode" in text
    assert "railway" not in text.lower()


def test_send_in_process_when_gateway_down():
    text = send_prompt(
        "Write a Python function that merges two lists.",
        base="http://127.0.0.1:4000",
        fetch_post=lambda *args, **kwargs: None,
    )
    assert "in-process" in text
    assert "model:" in text
    assert "est $:" in text
    assert "model-router" in text


def test_send_uses_gateway_payload():
    payload = {
        "model": "openai/gpt-4o-mini",
        "choices": [{"message": {"role": "assistant", "content": "Hello from the gateway."}}],
        "model_router": {
            "classification": {"task_type": "general_chat"},
            "decision": {"selected_model": "openai/gpt-4o-mini", "estimated_cost_usd": 0.0001},
        },
    }
    text = send_prompt(
        "hi",
        base="http://127.0.0.1:4000",
        fetch_post=lambda *args, **kwargs: (200, payload),
    )
    assert "via:        gateway" in text
    assert "general_chat" in text
    assert "Hello from the gateway." in text


def test_format_send_excerpt():
    text = format_send(
        via="gateway",
        classification_task="general_chat",
        model="openai/gpt-4o-mini",
        estimated_cost_usd=0.001,
        reply="word " * 200,
    )
    assert "..." in text
    assert len(text) < 800


def test_start_gateway_skips_when_health_up():
    spawned = []

    def fake_popen(*args, **kwargs):
        spawned.append(args)
        raise AssertionError("should not spawn")

    proc = start_gateway(
        "http://127.0.0.1:4000",
        popen=fake_popen,
        wait_health=lambda url, timeout=0.6: (200, {"status": "ok"}),
    )
    assert proc is None
    assert spawned == []


def test_cli_unknown_command_mentions_ui(capsys):
    assert cli_main(["not-a-command"]) == 2
    err = capsys.readouterr()
    assert "Unknown command" in err.err
    assert "ui" in err.out
