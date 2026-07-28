#!/usr/bin/env python3
"""Print draft policy floor hints from a stress bench results.jsonl (human review)."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results_jsonl", type=Path)
    args = ap.parse_args()
    rows = [json.loads(l) for l in args.results_jsonl.read_text().splitlines() if l.strip()]
    by_task_open: dict[str, list[float]] = defaultdict(list)
    miscls = 0
    n_cls = 0
    for r in rows:
        if r.get("family") == "open":
            by_task_open[r["task_type"]].append(1.0 if r.get("pass_") else 0.0)
        if r.get("classify_ok") is not None:
            n_cls += 1
            if not r["classify_ok"]:
                miscls += 1
    print("# Draft floor hints (DO NOT apply blindly)\n")
    if n_cls:
        print(f"Classifier error rate: {100*miscls/n_cls:.1f}% ({miscls}/{n_cls})\n")
    print("Suggested `min_accuracy_by_task` commentary:\n")
    for task, vals in sorted(by_task_open.items()):
        rate = statistics.mean(vals) if vals else 0
        if rate >= 0.7:
            action = "consider lowering floor 0.05"
        elif rate <= 0.3:
            action = "consider raising floor 0.05 or disable weak OSS"
        else:
            action = "keep"
        print(f"- {task}: OSS pass≈{rate:.0%} → {action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
