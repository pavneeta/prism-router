#!/usr/bin/env python3
"""Summarize logs/mirror.jsonl from --mirror-mode runs.

Usage:
  python scripts/mirror_summary.py
  python scripts/mirror_summary.py --path logs/mirror.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarize Prism mirror JSONL")
    ap.add_argument("--path", default="logs/mirror.jsonl")
    args = ap.parse_args()
    path = Path(args.path)
    if not path.exists():
        print(f"No mirror log at {path}")
        return

    n = 0
    winners: Counter[str] = Counter()
    auto_models: Counter[str] = Counter()
    primary_models: Counter[str] = Counter()
    tasks: Counter[str] = Counter()
    same = 0
    errors = 0

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        n += 1
        row = json.loads(line)
        tasks[str(row.get("task_type") or "?")] += 1
        primary = row.get("primary") or {}
        auto = row.get("auto") or {}
        primary_models[str(primary.get("requested_model") or primary.get("litellm_model") or "?")] += 1
        auto_models[str(auto.get("selected_model") or "?")] += 1
        if auto.get("status") == "skipped_same_model":
            same += 1
        if auto.get("status") == "error":
            errors += 1
        judge = row.get("judge")
        if isinstance(judge, dict) and judge.get("winner"):
            winners[str(judge["winner"])] += 1

    print(f"records={n} same_model_skips={same} auto_errors={errors}")
    print("tasks:", dict(tasks))
    print("primary models:", dict(primary_models))
    print("auto selected:", dict(auto_models))
    if winners:
        print("judge winners:", dict(winners))
    else:
        print("judge winners: (none — enable --mirror-judge)")


if __name__ == "__main__":
    main()
