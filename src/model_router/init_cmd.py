"""Write harness presets and run the local setup wizard.

``model-router init`` starts the background gateway (unless ``--no-start``)
and walks through a numbered setup. ``model-router init opencode|cursor|hermes``
stays non-interactive so scripts keep working.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError:  # pragma: no cover — rich is a package dependency

    class _Plain:
        def print(self, *args: Any, **kwargs: Any) -> None:
            end = kwargs.get("end", "\n")
            text = " ".join(str(arg) for arg in args)
            sys.stdout.write(text + (end or ""))
            sys.stdout.flush()

        def rule(self, title: str = "", **_kwargs: Any) -> None:
            print()
            print(str(title))
            print()

    class Console(_Plain):  # type: ignore[no-redef]
        def __init__(self, **_kwargs: Any) -> None:
            pass

    class Panel(str):  # type: ignore[no-redef]
        def __new__(cls, body: Any, **_kwargs: Any) -> "Panel":
            return str.__new__(cls, str(body))

    class Table:  # type: ignore[no-redef]
        def __init__(self, **_kwargs: Any) -> None:
            self._rows: list[tuple[str, ...]] = []

        def add_column(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def add_row(self, *cols: Any) -> None:
            self._rows.append(tuple(str(col) for col in cols))

        def __str__(self) -> str:
            return "\n".join("  ".join(row) for row in self._rows)

    class Text:  # type: ignore[no-redef]
        def __init__(self) -> None:
            self._parts: list[str] = []

        def append(self, text: str, style: str | None = None) -> "Text":  # noqa: ARG002
            self._parts.append(text)
            return self

        def __str__(self) -> str:
            return "".join(self._parts)

    class box:  # type: ignore[no-redef]
        ROUNDED = SIMPLE = None

from model_router import __version__
from model_router.daemon import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DaemonError,
    DaemonState,
    health_ok,
    inspect as inspect_daemon,
    listen_url,
    ready_status,
    resolve_home,
    start_daemon,
)

DEFAULT_WHY_PROMPT = "Write a Python function that merges two lists."
WIZARD_STEPS = 6

PLACEHOLDER_BASE = "https://<your-prism-host>/v1"
LOCAL_BASE = "http://127.0.0.1:4000/v1"

OPENCODE_PROVIDER = {
    "npm": "@ai-sdk/openai-compatible",
    "name": "Model-Router",
    "options": {
        "baseURL": PLACEHOLDER_BASE,
        "apiKey": "unused",
        "streaming": True,
        "headers": {"X-Session-Id": "opencode-local"},
    },
    "models": {"auto": {"name": "Auto (cache-aware route)"}},
}

CURSOR_NOTE = """# Point Cursor at Prism Router

Cursor does not ship a first-class Prism provider. Use the built-in
OpenAI-compatible override — do not invent extra settings keys.

1. Open **Settings → Models**
2. Enable **Override OpenAI Base URL**
3. Set the base URL to `{placeholder}`
   - Local example (after `model-router` is running): `{local}`
4. Set the model to `auto`
5. If the gateway has `MODEL_ROUTER_API_KEYS` set, paste that key in Cursor's
   API key field. Locally, with auth off, any non-empty value is fine.

Optional: send a stable session header if your Cursor build allows custom
headers (`X-Session-Id`) so affinity and task memory stick.

See also: https://prism-router-ten.vercel.app/docs
""".format(placeholder=PLACEHOLDER_BASE, local=LOCAL_BASE)

HERMES_SNIPPET = f"""# Hermes Agent → Prism Router (custom OpenAI-compatible endpoint)
# Merge into ~/.hermes/config.yaml (back up first).
#
# Local example (after `model-router` is running):
#   base_url: {LOCAL_BASE}

model:
  default: auto
  provider: custom
  base_url: {PLACEHOLDER_BASE}
  api_key: unused
"""

HARNESS_LABELS = {
    "opencode": "OpenCode   — write opencode.json",
    "cursor": "Cursor     — write .cursor/prism-router.md",
    "hermes": "Hermes     — write hermes-prism.snippet.yaml",
}

AskFn = Callable[[str, str], str]


def write_opencode(root: Path, *, base_url: str | None = None) -> Path:
    path = root / "opencode.json"
    data: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            data = {}
    default_base = base_url or PLACEHOLDER_BASE
    data.setdefault("$schema", "https://opencode.ai/config.json")
    data["model"] = "model-router/auto"
    providers = data.setdefault("provider", {})
    if not isinstance(providers, dict):
        providers = {}
        data["provider"] = providers
    existing = providers.get("model-router")
    if isinstance(existing, dict):
        merged = dict(existing)
        merged.setdefault("npm", OPENCODE_PROVIDER["npm"])
        merged.setdefault("name", OPENCODE_PROVIDER["name"])
        options = merged.get("options") if isinstance(merged.get("options"), dict) else {}
        for key, value in OPENCODE_PROVIDER["options"].items():
            if key == "baseURL":
                options.setdefault(key, default_base)
            else:
                options.setdefault(key, value)
        merged["options"] = options
        models = merged.get("models") if isinstance(merged.get("models"), dict) else {}
        models.setdefault("auto", {"name": "Auto (cache-aware route)"})
        merged["models"] = models
        providers["model-router"] = merged
    else:
        provider = json.loads(json.dumps(OPENCODE_PROVIDER))
        provider["options"]["baseURL"] = default_base
        providers["model-router"] = provider
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def write_cursor(root: Path, *, base_url: str | None = None) -> Path:
    dest_dir = root / ".cursor"
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / "prism-router.md"
    path.write_text(CURSOR_NOTE, encoding="utf-8")
    return path


def write_hermes(root: Path, *, base_url: str | None = None) -> Path:
    path = root / "hermes-prism.snippet.yaml"
    path.write_text(HERMES_SNIPPET, encoding="utf-8")
    return path


WRITERS = {
    "opencode": write_opencode,
    "cursor": write_cursor,
    "hermes": write_hermes,
}


def init_harness(name: str, root: Path, *, base_url: str | None = None) -> Path:
    writer = WRITERS.get(name)
    if writer is None:
        raise ValueError(f"unknown harness {name!r}; choose opencode, cursor, or hermes")
    return writer(root, base_url=base_url)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="model-router init",
        description=(
            "Start the local Prism gateway in the background and run a setup wizard. "
            "Pass a harness name (opencode, cursor, hermes) to write that preset "
            "non-interactively without starting the gateway."
        ),
    )
    ap.add_argument(
        "harness",
        nargs="?",
        choices=sorted(WRITERS),
        help="opencode / cursor / hermes — write that preset and exit (no wizard)",
    )
    ap.add_argument(
        "--dir",
        default=".",
        help="Project directory (default: cwd)",
    )
    ap.add_argument(
        "--no-start",
        action="store_true",
        help="Run the wizard without starting the background gateway",
    )
    ap.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Listen host for the background gateway (default: {DEFAULT_HOST})",
    )
    ap.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Listen port for the background gateway (default: {DEFAULT_PORT})",
    )
    ap.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Accept defaults (skip prompts; pair with --client to write a preset)",
    )
    ap.add_argument(
        "--client",
        choices=[*sorted(WRITERS), "skip"],
        default=None,
        help="Client preset to write during the wizard (default: skip with --yes)",
    )
    ap.add_argument(
        "--foreground",
        action="store_true",
        help="Run setup, then start the gateway in this terminal",
    )
    ap.add_argument(
        "--home",
        default=None,
        help="Daemon state directory (default $PRISM_ROUTER_HOME or ~/.prism-router)",
    )
    ap.add_argument(
        "--why-prompt",
        default=DEFAULT_WHY_PROMPT,
        help="Prompt for the routing preview",
    )
    return ap


def _ask(label: str, default: str, *, input_fn: AskFn | None = None) -> str:
    reader = input_fn or (lambda _label, _default: input(f"{_label}: "))
    try:
        typed = reader(label, default)
    except EOFError:
        return default
    if typed is None:
        return default
    raw = str(typed).strip()
    return raw or default


def _default_ask(label: str, default: str) -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"{label}{suffix}: ")


def _parse_port(raw: str, fallback: int) -> int:
    try:
        port = int(str(raw).strip())
    except (TypeError, ValueError):
        return fallback
    if 1 <= port <= 65535:
        return port
    return fallback


def _parse_harness_choice(raw: str) -> str | None:
    value = (raw or "").strip().lower()
    aliases = {
        "1": "opencode",
        "opencode": "opencode",
        "2": "cursor",
        "cursor": "cursor",
        "3": "hermes",
        "hermes": "hermes",
        "4": None,
        "skip": None,
        "": None,
    }
    if value in aliases:
        return aliases[value]
    return None


def _print_banner(console: Console) -> None:
    title = Text()
    title.append("  ◆  ", style="bold cyan")
    title.append("Prism Router", style="bold")
    title.append(f"  v{__version__}", style="dim")
    title.append("\n     Local OpenAI-compatible gateway + setup", style="dim")
    console.print(Panel(title, box=box.ROUNDED, border_style="cyan", padding=(0, 1)))


def _step(console: Console, index: int, total: int, title: str) -> None:
    console.print()
    console.rule(f"[bold cyan]Step {index}/{total}[/]  {title}", style="cyan")
    console.print()


def _print_providers(console: Console, flags: dict[str, bool]) -> None:
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold", pad_edge=False)
    table.add_column("Provider", style="white")
    table.add_column("Key")
    for name, present in flags.items():
        table.add_row(name, "[green]present[/]" if present else "[dim]missing[/]")
    console.print(table)
    console.print("[dim]Values are never printed. Add keys to .env on the gateway.[/]")


def _print_hints(console: Console, url: str) -> None:
    local_v1 = f"{url.rstrip('/')}/v1"
    console.print("Point an OpenAI-compatible client at this machine:\n")
    console.print(f'  export OPENAI_API_BASE="{local_v1}"')
    console.print("  # client key: any non-empty value locally (auth off by default)")
    console.print(f'  # self-hosted: export OPENAI_API_BASE="{PLACEHOLDER_BASE}"')


def _print_recap(
    console: Console,
    *,
    url: str,
    pid: int | None,
    harness: str | None,
    written: Path | None,
    started: bool,
) -> None:
    body = Text()
    body.append("  ✓  Setup complete\n\n", style="bold green")
    body.append("  Gateway   ", style="dim")
    body.append(f"{url}\n", style="bold")
    body.append("  PID       ", style="dim")
    body.append(f"{pid if pid else '—'}\n")
    if harness:
        body.append("  Harness   ", style="dim")
        body.append(f"{harness}")
        if written:
            body.append(f"  ({written})")
        body.append("\n")
    body.append("\n  Next\n", style="bold")
    body.append('    model-router why "Write a Python function that merges two lists."\n')
    body.append("    model-router ui\n")
    if started:
        body.append("    model-router status\n")
        body.append("    model-router stop\n")
    else:
        body.append("    model-router init          # start the background gateway\n")
        body.append("    model-router serve         # or run it in the foreground\n")
    console.print()
    console.print(Panel(body, box=box.ROUNDED, border_style="green", padding=(0, 1)))


def _write_harness_only(name: str, root: Path) -> int:
    path = init_harness(name, root)
    print(f"wrote {path}")
    print(f"placeholder base URL: {PLACEHOLDER_BASE}")
    print(f"local example:        {LOCAL_BASE}  (after `model-router` is running)")
    return 0


def run_wizard(
    *,
    root: Path,
    host: str,
    port: int,
    start: bool,
    assume_yes: bool = False,
    client: str | None = None,
    home: Path | None = None,
    foreground: bool = False,
    why_prompt: str = DEFAULT_WHY_PROMPT,
    input_fn: AskFn | None = None,
    console: Console | None = None,
    start_fn: Callable[..., DaemonState] | None = None,
    health_fn: Callable[[str, int], bool] | None = None,
    ready_fn: Callable[[str, int], str | None] | None = None,
    serve_fn: Callable[[list[str]], int] | None = None,
) -> int:
    from model_router.ui import provider_key_flags

    out = console or Console(highlight=False)
    ask = input_fn or _default_ask
    home = resolve_home(home)
    _print_banner(out)

    daemon: DaemonState | None = None
    if foreground:
        out.print()
        out.print("  Gateway will start in the foreground after setup")
    elif start:
        out.print()
        out.print("  Starting local gateway…")
        try:
            launcher = start_fn or start_daemon
            daemon = launcher(host, port, home=home)
        except DaemonError as exc:
            out.print(f"  [red]✗[/]  {exc}")
            return 1
        mark = "already running" if daemon.already_running else "listening"
        out.print(f"  [green]✓[/]  {mark} on {daemon.url}", end="")
        if daemon.pid:
            out.print(f"  [dim](pid {daemon.pid})[/]")
        else:
            out.print()
        host, port = daemon.host, daemon.port
    else:
        current = inspect_daemon(host=host, port=port, home=home)
        if current.running:
            daemon = current
            out.print()
            out.print(f"  [green]✓[/]  gateway already up at {current.url}")

    _step(out, 1, WIZARD_STEPS, "Provider keys")
    _print_providers(out, provider_key_flags())

    _step(out, 2, WIZARD_STEPS, "Listen address")
    if assume_yes:
        chosen_host, chosen_port = host, port
        out.print(f"  Host  {chosen_host}")
        out.print(f"  Port  {chosen_port}")
    else:
        chosen_host = _ask("Host", host, input_fn=ask)
        chosen_port = _parse_port(_ask("Port", str(port), input_fn=ask), port)
    if start and (chosen_host != host or chosen_port != port):
        out.print("  Restarting gateway on the new address…")
        try:
            from model_router.daemon import stop_daemon

            stop_daemon(home=home)
            launcher = start_fn or start_daemon
            daemon = launcher(chosen_host, chosen_port, home=home)
        except DaemonError as exc:
            out.print(f"  [red]✗[/]  {exc}")
            return 1
        host, port = chosen_host, chosen_port
    else:
        host, port = chosen_host, chosen_port
    url = listen_url(host, port)

    _step(out, 3, WIZARD_STEPS, "Client harness")
    for index, name in enumerate(("opencode", "cursor", "hermes"), start=1):
        out.print(f"  {index}) {HARNESS_LABELS[name]}")
    out.print("  4) Skip")
    written: Path | None = None
    harness: str | None = None
    preset = None if client in {None, "skip"} else client
    if assume_yes:
        harness = preset
        out.print(f"  Choice  {harness or 'skip'}")
        if harness:
            written = init_harness(harness, root, base_url=f"{url.rstrip('/')}/v1")
            out.print(f"  [green]✓[/]  wrote {written}")
    else:
        default_choice = {"opencode": "1", "cursor": "2", "hermes": "3"}.get(preset or "", "4")
        raw = _ask("Choice", default_choice, input_fn=ask)
        harness = _parse_harness_choice(raw)
        if harness:
            written = init_harness(harness, root, base_url=f"{url.rstrip('/')}/v1")
            out.print(f"  [green]✓[/]  wrote {written}")
        else:
            out.print("  skipped")

    _step(out, 4, WIZARD_STEPS, "Client hints")
    _print_hints(out, url)

    _step(out, 5, WIZARD_STEPS, "Health")
    check_health = health_fn or health_ok
    check_ready = ready_fn or ready_status
    healthy = check_health(host, port)
    out.print(f"  /health  {'ok' if healthy else 'unavailable'}")
    if healthy:
        ready_value = check_ready(host, port)
        if ready_value:
            out.print(f"  /ready   {ready_value}")

    _step(out, 6, WIZARD_STEPS, "Routing preview")
    from model_router.why import explain_prompt, format_explain

    prompt = (why_prompt or DEFAULT_WHY_PROMPT).strip() or DEFAULT_WHY_PROMPT
    out.print(f"  prompt: {prompt}")
    try:
        classification, decision = explain_prompt(prompt)
    except Exception as exc:  # noqa: BLE001 — wizard must finish without config cwd
        out.print(f"  could not preview routing ({exc})")
    else:
        for line in format_explain(classification, decision).splitlines():
            out.print(f"  {line}")

    pid = daemon.pid if daemon else None
    _print_recap(
        out,
        url=url,
        pid=pid,
        harness=harness,
        written=written,
        started=bool(daemon and daemon.running) or start,
    )
    if foreground:
        runner = serve_fn
        if runner is None:
            from model_router.cli import _serve

            runner = _serve
        return runner(["--host", host, "--port", str(port)])
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.dir).resolve()
    if args.harness:
        return _write_harness_only(args.harness, root)
    try:
        return run_wizard(
            root=root,
            host=args.host,
            port=args.port,
            start=not args.no_start and not args.foreground,
            assume_yes=args.yes,
            client=args.client,
            home=Path(args.home) if args.home else None,
            foreground=args.foreground,
            why_prompt=args.why_prompt,
        )
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
