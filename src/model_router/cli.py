"""Prism Router CLI — ``model-router`` / ``prism`` subcommands.

``model-router`` with no subcommand (or only serve flags) starts the gateway,
preserving the existing ``model-router --dry-run`` invocation.

``--help`` / ``--version`` are handled here so they are not swallowed by the
gateway argparse parser.
"""

from __future__ import annotations

import argparse
import sys
import textwrap

from model_router import __version__


def _serve(argv: list[str]) -> int:
    from model_router.gateway import main as gateway_main

    sys.argv = ["model-router", *argv]
    gateway_main()
    return 0


def add_serve_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("gateway (default command)")
    group.add_argument("--host", default=None, help="Bind host (default from settings)")
    group.add_argument("--port", type=int, default=None, help="Bind port (default from settings)")
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Route/classify only; do not call providers",
    )
    group.add_argument(
        "--mirror-mode",
        action="store_true",
        help="Also run auto path for passthrough requests; log both outputs to JSONL",
    )
    group.add_argument("--mirror-path", default=None, help="Mirror JSONL path")
    group.add_argument(
        "--mirror-judge",
        action="store_true",
        help="After mirror completions, score primary vs auto with a small LLM judge",
    )
    group.add_argument("--mirror-judge-model", default=None, help="Judge model id")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="model-router",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Prism Router — OpenAI-compatible gateway and local helpers",
        epilog=textwrap.dedent(
            """\
            Gateway
              model-router                 Start the gateway in the foreground
              model-router serve           Same as bare model-router (also: up)
              model-router --dry-run       Classify and route without calling providers
              model-router stop            Stop the background router started by init
              model-router status          Show whether the background router is running

            Setup
              model-router init            Start the router in the background and run setup
              model-router init --yes      Non-interactive setup (CI / scripts)
              model-router init opencode   Write an OpenCode preset only
              model-router ui              Interactive getting-started REPL

            Inspect
              model-router why "..."       Explain how a prompt would be routed
              model-router --version       Print the installed version

            Aliases: prism
            """
        ),
    )
    ap.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    add_serve_flags(ap)
    ap.add_argument(
        "command",
        nargs="?",
        help="init | stop | status | ui | why | serve | up (default: start the gateway)",
    )
    ap.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"-h", "--help"}:
        build_parser().print_help()
        return 0
    if argv and argv[0] in {"-V", "--version"}:
        print(f"model-router {__version__}")
        return 0

    if not argv or argv[0].startswith("-"):
        return _serve(argv)

    command, *rest = argv
    if command in {"serve", "gateway", "up"}:
        return _serve(rest)
    if command == "why":
        from model_router.why import main as why_main

        return why_main(rest)
    if command == "init":
        from model_router.init_cmd import main as init_main

        return init_main(rest)
    if command == "ui":
        from model_router.ui import main as ui_main

        return ui_main(rest)
    if command == "stop":
        from model_router.daemon import stop_main

        return stop_main(rest)
    if command == "status":
        from model_router.daemon import status_main

        return status_main(rest)

    build_parser().print_help()
    print(f"\nUnknown command: {command}", file=sys.stderr)
    return 2


build_root_parser = build_parser


if __name__ == "__main__":
    raise SystemExit(main())
