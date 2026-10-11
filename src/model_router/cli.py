"""Prism Router CLI — ``model-router`` / ``prism`` subcommands.

``model-router`` with no subcommand (or only serve flags) starts the gateway,
preserving the existing ``model-router --dry-run`` invocation.
"""

from __future__ import annotations

import argparse
import sys


def _serve(argv: list[str]) -> int:
    from model_router.gateway import main as gateway_main

    sys.argv = ["model-router", *argv]
    gateway_main()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-"):
        return _serve(argv)
    command = argv[0]
    rest = argv[1:]
    if command in {"serve", "gateway"}:
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

    ap = argparse.ArgumentParser(
        prog="model-router",
        description="Prism Router — OpenAI-compatible gateway and local helpers",
    )
    ap.add_argument(
        "command",
        nargs="?",
        help="serve (default) | why | init | ui",
    )
    ap.print_help()
    print(f"\nUnknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
