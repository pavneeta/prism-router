"""Git history scrub (#13): classify, redact, rewrite, and keep the public tree clean."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.git_history_scrub import (
    PLACEHOLDER_HOST,
    concrete_railway_hosts,
    env_is_tracked,
    filter_repo_replace_lines,
    is_allowed_railway_host,
    is_test_shaped_secret,
    iter_scan_files,
    iter_secret_tokens,
    main,
    redact_host,
    redact_secret,
    rewrite_working_tree,
    scan_git_history,
    scan_tree,
    scrub_text,
)

REPO = Path(__file__).resolve().parents[1]


def _host(label: str) -> str:
    return f"{label}.up.railway.app"


def test_placeholder_host_is_allowed():
    assert is_allowed_railway_host(PLACEHOLDER_HOST)
    assert concrete_railway_hosts(f"curl https://{PLACEHOLDER_HOST}/health") == []


def test_concrete_host_is_flagged():
    leak = _host("leaky-fixture")
    assert concrete_railway_hosts(f"export OPENAI_API_BASE=https://{leak}/v1") == [leak]


def test_wildcard_docs_form_is_not_a_host_leak():
    assert concrete_railway_hosts("generate public *.up.railway.app host") == []


def test_scrub_text_replaces_only_concrete_hosts():
    leak = _host("leaky-fixture")
    src = f"live {leak} and docs {PLACEHOLDER_HOST}"
    assert scrub_text(src) == f"live {PLACEHOLDER_HOST} and docs {PLACEHOLDER_HOST}"


def test_redact_host_hides_label():
    leak = _host("leaky-fixture")
    hidden = redact_host(leak)
    assert hidden.endswith(".up.railway.app")
    assert "leaky-fixture" not in hidden
    assert hidden.startswith("le")


def test_test_shaped_secrets_are_ignored():
    assert is_test_shaped_secret("sk-abcdefghijklmnopqrstuvwxyz012345")
    assert iter_secret_tokens("leak sk-abcdefghijklmnopqrstuvwxyz012345") == []
    assert iter_secret_tokens("MODEL_ROUTER_API_KEYS=pr_replace_me_with_a_long_random_string") == []


def test_high_entropy_secret_is_flagged_and_redacted():
    token = "sk-proj-" + "0a1b2c3d4e5f6g7h8i9j"
    assert iter_secret_tokens(f"key={token}") == [token]
    assert "0a1b2c3d" not in redact_secret(token)


def test_public_tree_scan_covers_docs():
    files = {str(path.relative_to(REPO.resolve())) for path in iter_scan_files(REPO)}
    assert "README.md" in files
    assert "docs/internal/OPEN_SOURCE.md" in files


def test_public_tree_has_no_concrete_hosts_or_secrets():
    findings = scan_tree(REPO)
    assert findings == [], [f"{item.kind} {item.path}:{item.line}" for item in findings]


def test_env_is_not_tracked():
    assert env_is_tracked(REPO) is False


def test_filter_repo_lines_are_pattern_only():
    lines = filter_repo_replace_lines()
    assert lines
    joined = "\n".join(lines)
    assert "regex:" in joined
    assert PLACEHOLDER_HOST in joined
    assert "leaky-fixture" not in joined
    assert not concrete_railway_hosts(joined)


def test_rewrite_working_tree(tmp_path: Path):
    leak = _host("leaky-fixture")
    target = tmp_path / "README.md"
    target.write_text(f"demo {leak}\nkeep {PLACEHOLDER_HOST}\n", encoding="utf-8")
    assert rewrite_working_tree(tmp_path) == 1
    text = target.read_text(encoding="utf-8")
    assert leak not in text
    assert text.count(PLACEHOLDER_HOST) == 2


def test_scan_history_finds_redacted_commit(tmp_path: Path):
    leak = _host("leaky-fixture")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "scrub@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Scrub Test"], cwd=tmp_path, check=True)
    (tmp_path / "note.md").write_text(f"url https://{leak}/v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "note.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "plant leak"], cwd=tmp_path, check=True)

    findings = scan_git_history(tmp_path)
    assert findings
    assert all("leaky-fixture" not in item.excerpt for item in findings)
    assert all(item.kind == "railway_host" for item in findings)


def test_cli_scan_clean_and_dirty(tmp_path: Path, capsys):
    (tmp_path / "ok.md").write_text(f"use {PLACEHOLDER_HOST}\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    assert main(["scan", "--root", str(tmp_path)]) == 0
    capsys.readouterr()

    leak = _host("leaky-fixture")
    (tmp_path / "bad.md").write_text(f"https://{leak}/health\n", encoding="utf-8")
    assert main(["scan", "--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "railway_host" in out
    assert "leaky-fixture" not in out


def test_cli_replacements_and_rewrite_guard(capsys):
    assert main(["replacements"]) == 0
    out = capsys.readouterr().out
    assert "regex:" in out
    assert PLACEHOLDER_HOST in out
    assert main(["rewrite"]) == 2


def test_cli_working_tree_rewrite(tmp_path: Path):
    leak = _host("leaky-fixture")
    (tmp_path / "docs.md").write_text(f"{leak}\n", encoding="utf-8")
    assert main(["rewrite", "--working-tree-only", "--root", str(tmp_path)]) == 0
    assert (tmp_path / "docs.md").read_text(encoding="utf-8") == f"{PLACEHOLDER_HOST}\n"
