from pathlib import Path

from model_router.cli import build_root_parser, main as cli_main

_REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"


def _prepare_wizard_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODEL_ROUTER_CONFIG_DIR", str(_REPO_CONFIG))
    monkeypatch.setenv("MODEL_ROUTER_HOME", str(tmp_path / "home"))
    from model_router.config import get_settings

    get_settings.cache_clear()
from model_router.init_cmd import (
    LOCAL_BASE,
    PLACEHOLDER_BASE,
    build_parser as build_init_parser,
    init_harness,
    write_cursor,
    write_hermes,
    write_opencode,
)
from model_router.why import explain_prompt, main as why_main


def test_why_explains_codegen(capsys):
    assert why_main(["Write a Python function that merges two sorted lists."]) == 0
    out = capsys.readouterr().out
    assert "task:       code_generation" in out
    assert "difficulty: easy" in out
    assert "model:" in out
    assert "est $:" in out


def test_why_json(capsys):
    assert why_main(["--json", "Write a haiku about routing."]) == 0
    out = capsys.readouterr().out
    assert '"task_type": "creative_writing"' in out
    assert '"difficulty"' in out


def test_explain_prompt_returns_decision():
    classification, decision = explain_prompt("Hello, how are you?")
    assert classification.task_type == "general_chat"
    assert decision.selected_model
    assert decision.estimated_cost_usd >= 0


def test_cli_why_subcommand(capsys):
    assert cli_main(["why", "Please summarize this article into key points."]) == 0
    assert "summarization" in capsys.readouterr().out


def test_init_opencode_writes_placeholder(tmp_path: Path):
    path = write_opencode(tmp_path)
    data = path.read_text(encoding="utf-8")
    assert PLACEHOLDER_BASE in data
    assert "X-Session-Id" in data
    assert "model-router/auto" in data
    # Local example is documented by the CLI, not required inside JSON.


def test_init_opencode_preserves_existing_keys(tmp_path: Path):
    existing = tmp_path / "opencode.json"
    existing.write_text(
        '{"model":"other","provider":{"keep":{"name":"stay"},'
        '"model-router":{"options":{"baseURL":"https://already.example/v1"}}}}',
        encoding="utf-8",
    )
    write_opencode(tmp_path)
    import json

    data = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert data["provider"]["keep"]["name"] == "stay"
    assert data["provider"]["model-router"]["options"]["baseURL"] == "https://already.example/v1"
    assert data["model"] == "model-router/auto"


def test_init_cursor_note(tmp_path: Path):
    path = write_cursor(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "Settings → Models" in text
    assert "Override OpenAI Base URL" in text
    assert PLACEHOLDER_BASE in text
    assert LOCAL_BASE in text
    assert "auto" in text


def test_init_hermes_snippet(tmp_path: Path):
    path = write_hermes(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "provider: custom" in text
    assert PLACEHOLDER_BASE in text
    assert LOCAL_BASE in text


def test_cli_init_opencode(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli_main(["init", "opencode", "--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "opencode.json" in out
    assert (tmp_path / "opencode.json").exists()
    assert init_harness("opencode", tmp_path).name == "opencode.json"


def test_cli_ui_status_flag(capsys, monkeypatch):
    monkeypatch.setattr(
        "model_router.ui.fetch_json",
        lambda url, timeout=0.6: None,
    )
    assert cli_main(["ui", "--status"]) == 0
    out = capsys.readouterr().out
    assert "gateway:" in out
    assert "down" in out
    assert "model-router" in out


def test_cli_ui_why_flag(capsys):
    assert cli_main(["ui", "--why", "Please summarize this article into key points."]) == 0
    assert "summarization" in capsys.readouterr().out


def test_cli_bare_still_serves(monkeypatch):
    called = {}

    def fake_serve(argv):
        called["argv"] = argv
        return 0

    monkeypatch.setattr("model_router.cli._serve", fake_serve)
    assert cli_main([]) == 0
    assert called["argv"] == []
    assert cli_main(["--dry-run"]) == 0
    assert called["argv"] == ["--dry-run"]
    assert cli_main(["up", "--host", "127.0.0.1"]) == 0
    assert called["argv"] == ["--host", "127.0.0.1"]
    assert cli_main(["serve"]) == 0
    assert called["argv"] == []


def test_cli_root_help_lists_init(capsys):
    assert cli_main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "init" in out
    assert "serve" in out
    assert "stop" in out
    assert "status" in out


def test_cli_version(capsys):
    assert cli_main(["--version"]) == 0
    assert capsys.readouterr().out.strip()


def test_cli_unknown_command(capsys):
    assert cli_main(["nope"]) == 2
    err = capsys.readouterr().err
    assert "Unknown command: nope" in err


def test_init_parser_harness_optional():
    args = build_init_parser().parse_args(["--no-start"])
    assert args.harness is None
    assert args.no_start is True
    args = build_init_parser().parse_args(["opencode", "--dir", "/tmp"])
    assert args.harness == "opencode"
    yes = build_init_parser().parse_args(["--yes", "--client", "opencode", "--port", "4123"])
    assert yes.yes is True
    assert yes.client == "opencode"
    assert yes.port == 4123
    root = build_root_parser().parse_args([])
    assert root.command is None


def test_init_yes_starts_mocked_daemon(tmp_path: Path, capsys, monkeypatch):
    from model_router.daemon import DaemonState

    called: dict[str, object] = {}

    def fake_start(host, port, home=None, extra_args=None, **_kwargs):
        called["host"] = host
        called["port"] = port
        called["home"] = home
        return DaemonState(
            running=True,
            pid=99,
            host=host,
            port=port,
            url=f"http://{host}:{port}",
            log_path=tmp_path / "gateway.log",
            pid_path=tmp_path / "gateway.pid",
            started=True,
        )

    monkeypatch.setenv("MODEL_ROUTER_CONFIG_DIR", str(_REPO_CONFIG))
    from model_router.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr("model_router.init_cmd.start_daemon", fake_start)
    monkeypatch.setattr("model_router.init_cmd.health_ok", lambda host, port: True)
    monkeypatch.setattr("model_router.init_cmd.ready_status", lambda host, port: "ready")
    assert (
        cli_main(
            [
                "init",
                "--yes",
                "--host",
                "127.0.0.1",
                "--port",
                "4123",
                "--dir",
                str(tmp_path),
                "--home",
                str(tmp_path / "home"),
            ]
        )
        == 0
    )
    assert called["port"] == 4123
    out = capsys.readouterr().out
    assert "4123" in out
    assert "/health" in out
    assert "ready" in out
    assert "Setup complete" in out
    assert "pid 99" in out.lower() or "99" in out


def test_init_wizard_no_start_mocked_stdin(tmp_path: Path, capsys, monkeypatch):
    _prepare_wizard_env(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-must-not-print")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("\n\n1\n"))
    assert cli_main(["init", "--no-start", "--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Setup complete" in out
    assert "Step 1/6" in out
    assert "openai" in out.lower()
    assert "present" in out
    assert "sk-secret-must-not-print" not in out
    assert "OPENAI_API_BASE=" in out
    assert "http://127.0.0.1:4000/v1" in out
    assert (tmp_path / "opencode.json").exists()
    assert "railway" not in out.lower()
    assert "task:" in out
    assert "/health" in out


def test_init_wizard_yes_skips_harness(tmp_path: Path, capsys, monkeypatch):
    _prepare_wizard_env(monkeypatch, tmp_path)
    assert cli_main(["init", "--no-start", "--yes", "--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Setup complete" in out
    assert not (tmp_path / "opencode.json").exists()
    assert "model-router why" in out


def test_init_wizard_yes_client_opencode(tmp_path: Path, capsys, monkeypatch):
    _prepare_wizard_env(monkeypatch, tmp_path)
    assert cli_main([
        "init",
        "--no-start",
        "--yes",
        "--client",
        "opencode",
        "--dir",
        str(tmp_path),
    ]) == 0
    out = capsys.readouterr().out
    assert "Setup complete" in out
    assert (tmp_path / "opencode.json").exists()
    assert "opencode.json" in out
    assert "sk-" not in out


def test_init_wizard_custom_listen(tmp_path: Path, capsys, monkeypatch):
    _prepare_wizard_env(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("127.0.0.1\n4123\n4\n"))
    assert cli_main(["init", "--no-start", "--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "http://127.0.0.1:4123" in out
    assert "skipped" in out.lower() or "skip" in out.lower()
