"""Write harness presets: OpenCode, Cursor paste-note, Hermes snippet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

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


def write_opencode(root: Path) -> Path:
    path = root / "opencode.json"
    data: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            data = {}
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
            options.setdefault(key, value)
        merged["options"] = options
        models = merged.get("models") if isinstance(merged.get("models"), dict) else {}
        models.setdefault("auto", {"name": "Auto (cache-aware route)"})
        merged["models"] = models
        providers["model-router"] = merged
    else:
        providers["model-router"] = json.loads(json.dumps(OPENCODE_PROVIDER))
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def write_cursor(root: Path) -> Path:
    dest_dir = root / ".cursor"
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / "prism-router.md"
    path.write_text(CURSOR_NOTE, encoding="utf-8")
    return path


def write_hermes(root: Path) -> Path:
    path = root / "hermes-prism.snippet.yaml"
    path.write_text(HERMES_SNIPPET, encoding="utf-8")
    return path


WRITERS = {
    "opencode": write_opencode,
    "cursor": write_cursor,
    "hermes": write_hermes,
}


def init_harness(name: str, root: Path) -> Path:
    writer = WRITERS.get(name)
    if writer is None:
        raise ValueError(f"unknown harness {name!r}; choose opencode, cursor, or hermes")
    return writer(root)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="model-router init",
        description="Write a Prism Router harness preset into the current project.",
    )
    ap.add_argument(
        "harness",
        choices=sorted(WRITERS),
        help="opencode writes opencode.json; cursor writes a paste-ready note; hermes writes a yaml snippet",
    )
    ap.add_argument(
        "--dir",
        default=".",
        help="Project directory (default: cwd)",
    )
    args = ap.parse_args(argv)
    root = Path(args.dir).resolve()
    path = init_harness(args.harness, root)
    print(f"wrote {path}")
    print(f"placeholder base URL: {PLACEHOLDER_BASE}")
    print(f"local example:        {LOCAL_BASE}  (after `model-router` is running)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
