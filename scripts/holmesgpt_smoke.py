#!/usr/bin/env python3
"""HolmesGPT-shaped smoke against a running Prism Router gateway.

Simulates Holmes' OpenAI-compatible + LiteLLM path: model openai/auto with tools
(function calling is required by HolmesGPT).

Usage:
  # gateway must be up on :4000
  python scripts/holmesgpt_smoke.py
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

    # Explain path — no provider spend; validates openai/auto + tools classify
    explain = _post(
        "/v1/router/explain",
        {
            "model": "openai/auto",
            "messages": [
                {
                    "role": "user",
                    "content": "Use tools to diagnose CrashLoopBackOff on the payments pod.",
                }
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "kubectl_logs",
                        "description": "Fetch pod logs",
                        "parameters": {
                            "type": "object",
                            "properties": {"pod": {"type": "string"}},
                        },
                    },
                }
            ],
        },
        headers={"X-Session-Id": "holmesgpt-smoke"},
    )
    task = (explain.get("classification") or {}).get("task_type")
    selected = (explain.get("decision") or {}).get("selected_model")
    print("explain task:", task)
    print("explain selected:", selected)
    if not selected:
        print("FAIL: no routing decision for openai/auto")
        return 1

    # Live/dry chat with tools (dry-run still returns content)
    chat = _post(
        "/v1/chat/completions",
        {
            "model": "openai/auto",
            "temperature": 0,
            "max_tokens": 64,
            "messages": [
                {
                    "role": "user",
                    "content": "Reply with exactly: holmesgpt-smoke-ok",
                }
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "kubectl_get",
                        "description": "List k8s resources",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        },
        headers={"X-Session-Id": "holmesgpt-smoke"},
    )
    content = (chat.get("choices") or [{}])[0].get("message", {}).get("content")
    decision = ((chat.get("model_router") or {}).get("decision") or {}).get(
        "selected_model"
    )
    print("chat selected:", decision)
    print("chat content:", content)
    if not content and not (chat.get("choices") or [{}])[0].get("message", {}).get(
        "tool_calls"
    ):
        # dry-run always has content; live may tool-call — either is OK
        print("FAIL: empty content and no tool_calls")
        return 1

    with urllib.request.urlopen(
        BASE + "/v1/router/sessions/holmesgpt-smoke", timeout=10
    ) as resp:
        rollup = json.loads(resp.read().decode())
    print("session:", json.dumps(rollup, indent=2)[:400])

    holmes = shutil.which("holmes")
    if holmes:
        print("holmes CLI found:", holmes)
        subprocess.run([holmes, "--help"], check=False)
    else:
        print("holmes CLI not installed — HTTP smoke only (see docs/HOLMESGPT.md)")

    print("PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        print("HTTPError", exc.read().decode()[:500])
        raise SystemExit(1) from exc
