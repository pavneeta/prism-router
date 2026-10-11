#!/usr/bin/env python3
"""Scan and rewrite leaked Railway hosts / secret-shaped tokens.

Issue #13. The current tree uses ``<your-service>`` placeholders only. Older
commits may still contain a concrete ``*.up.railway.app`` hostname. Rewriting
published history needs ``git filter-repo`` and an explicit force-push — this
script never pushes.

Usage:
  python scripts/git_history_scrub.py scan
  python scripts/git_history_scrub.py scan --history
  python scripts/git_history_scrub.py replacements
  python scripts/git_history_scrub.py rewrite --working-tree-only
  python scripts/git_history_scrub.py rewrite --i-understand-this-rewrites-history
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PLACEHOLDER_LABEL = "<your-service>"
PLACEHOLDER_HOST = f"{PLACEHOLDER_LABEL}.up.railway.app"

# Concrete DNS label or the documented placeholder. Does not match ``*.up.railway.app``.
RAILWAY_HOST_RE = re.compile(
    r"(?P<host>(?P<label><your-service>|[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)"
    r"\.up\.railway\.app)",
    re.I,
)

# High-entropy provider key shapes. Documentation that only mentions ``sk-`` is ignored.
SECRET_RE = re.compile(
    r"(?i)\b(?:"
    r"sk-ant-[a-z0-9_-]{16,}"
    r"|sk-proj-[a-z0-9_-]{16,}"
    r"|sk-[a-z0-9_-]{20,}"
    r"|fw_[a-z0-9_-]{16,}"
    r"|tgp_v1_[a-z0-9_-]{16,}"
    r"|gsk_[a-z0-9_-]{16,}"
    r"|pr_[A-Za-z0-9_-]{20,}"
    r")\b"
)

_TEST_SECRET_BODIES = frozenset(
    {
        "abcdefghijklmnopqrstuvwxyz012345",
        "secret",
        "secret-must-not-print",
        "secret-should-not-leak",
        "replace_me_with_a_long_random_string",
        "your_long_random_client_key",
    }
)
_DOC_SECRET_HINTS = ("your", "replace", "example", "dummy", "placeholder", "xxxx")

SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".worktrees",
        ".venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".vercel",
        ".hallmark",
        "stress_runs",
    }
)

TEXT_SUFFIXES = frozenset(
    {
        ".md",
        ".py",
        ".yml",
        ".yaml",
        ".toml",
        ".html",
        ".txt",
        ".sh",
        ".example",
        ".cfg",
        ".ini",
        ".css",
        ".js",
        ".json",
        ".svg",
        ".rst",
    }
)
TEXT_NAMES = frozenset({"Dockerfile", "Makefile", "LICENSE", "Procfile", "CURSOR.md"})

REWRITE_FLAG = "--i-understand-this-rewrites-history"


@dataclass(frozen=True)
class Finding:
    kind: str
    path: str
    line: int | None
    excerpt: str


def is_allowed_railway_host(host: str) -> bool:
    label = host.split(".up.railway.app", 1)[0]
    return label.lower() == PLACEHOLDER_LABEL


def redact_host(host: str) -> str:
    label = host.split(".up.railway.app", 1)[0]
    if len(label) <= 2:
        hidden = "*" * len(label)
    else:
        hidden = label[:2] + ("*" * (len(label) - 2))
    return f"{hidden}.up.railway.app"


def redact_secret(token: str) -> str:
    prefix, _, _rest = token.partition("-")
    if token.lower().startswith("sk-ant-"):
        return "sk-ant-[REDACTED]"
    if token.lower().startswith("sk-proj-"):
        return "sk-proj-[REDACTED]"
    if "_" in prefix:
        return f"{prefix}_[REDACTED]"
    return f"{prefix}-[REDACTED]"


def iter_railway_hosts(text: str) -> list[str]:
    return [match.group("host") for match in RAILWAY_HOST_RE.finditer(text)]


def concrete_railway_hosts(text: str) -> list[str]:
    return [host for host in iter_railway_hosts(text) if not is_allowed_railway_host(host)]


def is_test_shaped_secret(token: str) -> bool:
    lowered = token.lower()
    for prefix in ("sk-ant-", "sk-proj-", "sk-", "fw_", "tgp_v1_", "gsk_", "pr_"):
        if lowered.startswith(prefix):
            body = token[len(prefix) :]
            return body in _TEST_SECRET_BODIES or any(hint in body.lower() for hint in _DOC_SECRET_HINTS)
    return False


def iter_secret_tokens(text: str) -> list[str]:
    return [match.group(0) for match in SECRET_RE.finditer(text) if not is_test_shaped_secret(match.group(0))]


def scrub_text(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        if is_allowed_railway_host(match.group("host")):
            return match.group(0)
        return PLACEHOLDER_HOST

    return RAILWAY_HOST_RE.sub(_replace, text)


def filter_repo_replace_lines() -> list[str]:
    """git-filter-repo --replace-text lines. Pattern-only; no concrete hostname."""
    return [
        rf"regex:[A-Za-z0-9][A-Za-z0-9-]*\.up\.railway\.app==>{PLACEHOLDER_HOST}",
    ]


def _is_text_file(path: Path) -> bool:
    if path.name in TEXT_NAMES:
        return True
    return path.suffix.lower() in TEXT_SUFFIXES


def iter_scan_files(root: Path) -> list[Path]:
    root = root.resolve()
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIR_NAMES for part in rel_parts):
            continue
        if not _is_text_file(path):
            continue
        files.append(path)
    return sorted(files)


def _findings_in_text(text: str, path: str) -> list[Finding]:
    found: list[Finding] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for host in concrete_railway_hosts(line):
            found.append(
                Finding(
                    kind="railway_host",
                    path=path,
                    line=line_no,
                    excerpt=redact_host(host),
                )
            )
        for token in iter_secret_tokens(line):
            found.append(
                Finding(
                    kind="secret",
                    path=path,
                    line=line_no,
                    excerpt=redact_secret(token),
                )
            )
    return found


def scan_tree(root: Path) -> list[Finding]:
    root = root.resolve()
    findings: list[Finding] = []
    for path in iter_scan_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(path.relative_to(root))
        findings.extend(_findings_in_text(text, rel))
    return findings


def scan_git_history(repo: Path) -> list[Finding]:
    rev_list = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--all"],
        check=True,
        capture_output=True,
        text=True,
    )
    revs = [line for line in rev_list.stdout.splitlines() if line]
    if not revs:
        return []
    pattern = r"[A-Za-z0-9][A-Za-z0-9-]*\.up\.railway\.app"
    proc = subprocess.run(
        ["git", "-C", str(repo), "grep", "-I", "-n", "-E", pattern, *revs],
        capture_output=True,
        text=True,
    )
    findings: list[Finding] = []
    seen: set[tuple[str, str, int | None, str]] = set()
    for raw in proc.stdout.splitlines():
        # commit:path:line:text  (path may contain colons; take first three splits)
        parts = raw.split(":", 3)
        if len(parts) < 4:
            continue
        commit, path, line_s, body = parts
        try:
            line_no = int(line_s)
        except ValueError:
            line_no = None
        for host in concrete_railway_hosts(body):
            excerpt = redact_host(host)
            key = (commit, path, line_no, excerpt)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                Finding(
                    kind="railway_host",
                    path=f"{commit[:12]}:{path}",
                    line=line_no,
                    excerpt=excerpt,
                )
            )
    return findings


def rewrite_working_tree(root: Path) -> int:
    changed = 0
    for path in iter_scan_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scrubbed = scrub_text(text)
        if scrubbed != text:
            path.write_text(scrubbed, encoding="utf-8")
            changed += 1
    return changed


def env_is_tracked(repo: Path) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(repo), "ls-files", ".env"],
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(proc.stdout.strip())


def _print_findings(findings: list[Finding]) -> None:
    for item in findings:
        loc = f"{item.path}:{item.line}" if item.line is not None else item.path
        print(f"{item.kind:12} {loc}  {item.excerpt}")


def _cmd_scan(root: Path, history: bool) -> int:
    rc = 0
    if env_is_tracked(root):
        print("secret       .env  tracked (must be gitignored)")
        rc = 1
    tree = scan_tree(root)
    if tree:
        _print_findings(tree)
        rc = 1
    else:
        print("tree: clean (no concrete Railway hosts or secret-shaped tokens)")
    if history:
        hist = scan_git_history(root)
        if hist:
            _print_findings(hist)
            print(
                f"history: {len(hist)} redacted hit(s). "
                "Rewrite with git-filter-repo; this tool does not force-push."
            )
            rc = 1
        else:
            print("history: clean")
    return rc


def _cmd_replacements() -> int:
    for line in filter_repo_replace_lines():
        print(line)
    return 0


def _cmd_rewrite(root: Path, *, history: bool, working_tree: bool) -> int:
    if working_tree:
        changed = rewrite_working_tree(root)
        print(f"working tree: replaced concrete hosts in {changed} file(s)")
        return 0
    if not history:
        print(
            "rewrite refused: pass --working-tree-only or "
            f"{REWRITE_FLAG} (never force-pushes).",
            file=sys.stderr,
        )
        return 2
    replace_text = "\n".join(filter_repo_replace_lines()) + "\n"
    replacements = root / ".git" / "history-scrub-replacements.txt"
    replacements.parent.mkdir(parents=True, exist_ok=True)
    replacements.write_text(replace_text, encoding="utf-8")
    try:
        subprocess.run(["git", "filter-repo", "--help"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        print(
            "git-filter-repo is not installed. Install it, then from a fresh clone:\n"
            f"  git filter-repo --replace-text {replacements} "
            f"--replace-message {replacements}\n"
            "Do not force-push to main without explicit approval.",
            file=sys.stderr,
        )
        return 2
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "filter-repo",
            "--replace-text",
            str(replacements),
            "--replace-message",
            str(replacements),
        ],
        check=True,
    )
    print("history rewritten locally. Review, then force-push only with explicit approval.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Report leaks in the current tree (and optional history)")
    scan.add_argument(
        "--history",
        action="store_true",
        help="Also scan git blobs (redacted). Exit 1 if historical hosts remain.",
    )
    scan.add_argument("--root", type=Path, default=ROOT)

    sub.add_parser("replacements", help="Print git-filter-repo --replace-text lines")

    rewrite = sub.add_parser("rewrite", help="Replace concrete hosts (never pushes)")
    rewrite.add_argument("--working-tree-only", action="store_true")
    rewrite.add_argument(REWRITE_FLAG, dest="rewrite_history", action="store_true")
    rewrite.add_argument("--root", type=Path, default=ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "scan":
        return _cmd_scan(args.root.resolve(), history=args.history)
    if args.command == "replacements":
        return _cmd_replacements()
    if args.command == "rewrite":
        return _cmd_rewrite(
            args.root.resolve(),
            history=args.rewrite_history,
            working_tree=args.working_tree_only,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
