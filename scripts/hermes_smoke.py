#!/usr/bin/env python3
"""Hermes-shaped smoke against a running Prism Router gateway.

Simulates what Hermes sends (OpenAI-compatible custom endpoint) and optionally
invokes `hermes` CLI if installed.

Usage:
  # gateway must be up on :4000
  python scripts/hermes_smoke.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:4000"


def _post(path: str, payload: dict, headers: dict | None = None) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=5) as resp:
            health = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: gateway not reachable at {BASE}: {exc}")
        return 1
    print("health:", health)

    # Hermes custom provider shape
    chat = _post(
        "/v1/chat/completions",
        {
            "model": "auto",
            "temperature": 0,
            "max_tokens": 32,
            "messages": [
                {
                    "role": "user",
                    "content": "Reply with exactly: hermes-smoke-ok",
                }
            ],
        },
        headers={"X-Session-Id": "hermes-smoke"},
    )
    content = (chat.get("choices") or [{}])[0].get("message", {}).get("content")
    selected = ((chat.get("model_router") or {}).get("decision") or {}).get("selected_model")
    print("chat selected:", selected)
    print("chat content:", content)
    if not content:
        print("FAIL: empty content")
        return 1

    # Session rollup
    with urllib.request.urlopen(BASE + "/v1/router/sessions/hermes-smoke", timeout=10) as resp:
        rollup = json.loads(resp.read().decode())
    print("session:", json.dumps(rollup, indent=2)[:500])

    hermes = shutil.which("hermes")
    if hermes:
        print("hermes CLI found:", hermes)
        # Non-destructive version check
        subprocess.run([hermes, "--help"], check=False)
    else:
        print("hermes CLI not installed — HTTP smoke only (see docs/HERMES.md)")

    print("PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print("HTTPError", exc.read().decode()[:500])
        raise SystemExit(1) from exc
