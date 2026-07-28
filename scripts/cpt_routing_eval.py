#!/usr/bin/env python3
"""CLI for offline CPT-style routing distribution (no GPU, no network).

Usage:
  python scripts/cpt_routing_eval.py
  pytest tests/test_cpt_routing.py
"""

from __future__ import annotations

import json
import sys

from model_router.cpt_eval import run_eval


def main() -> int:
    rows = run_eval()
    strong = sum(1 for r in rows if r["bucket"] == "strong")
    cheap = sum(1 for r in rows if r["bucket"] == "cheap")
    print("CPT-style offline routing distribution")
    print(f"  cases={len(rows)}  strong={strong}  cheap={cheap}  other={len(rows) - strong - cheap}")
    print()
    for r in rows:
        print(
            f"  [{r['bucket']:6}] {r['name']:24} "
            f"task={r['task_type']:18} → {r['selected_model']}"
        )
    print()
    print(json.dumps({"rows": rows, "strong": strong, "cheap": cheap}, indent=2, default=str))

    task_mismatches = [
        r for r in rows if r["expect_task"] and r["task_type"] != r["expect_task"]
    ]
    if task_mismatches:
        for r in task_mismatches:
            print(f"FAIL: {r['name']}: got {r['task_type']} expected {r['expect_task']}")
        return 1

    chat_rows = [r for r in rows if r["task_type"] == "general_chat"]
    if chat_rows and not any(r["bucket"] == "cheap" for r in chat_rows):
        print("FAIL: expected at least one cheap general_chat route")
        return 1

    code_rows = [r for r in rows if r["task_type"] in {"code_generation", "code_review_debug"}]
    if not code_rows:
        print("FAIL: expected code tasks in harness set")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
