from pathlib import Path

from model_router.cli import main as cli_main
from model_router.init_cmd import (
    LOCAL_BASE,
    PLACEHOLDER_BASE,
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
