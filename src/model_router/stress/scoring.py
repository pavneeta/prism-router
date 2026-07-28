"""Deterministic (+ optional LLM-judge) scorers for stress bench scenarios."""

from __future__ import annotations

import ast
import json
import re
import traceback
from typing import Any


def _extract_code(text: str) -> str:
    fence = re.search(r"```(?:python)?\n(.*?)```", text, re.S | re.I)
    if fence:
        return fence.group(1).strip()
    return text.strip()


def _run_python(code: str, setup: str, call: str) -> Any:
    ns: dict[str, Any] = {}
    exec(compile(code, "<candidate>", "exec"), ns, ns)  # noqa: S102
    if setup:
        exec(compile(setup, "<setup>", "exec"), ns, ns)  # noqa: S102
    return eval(call, ns, ns)  # noqa: S307


def _answer_tail_int(text: str) -> int | None:
    m = re.search(r"Answer:\s*(-?\d+)", text, re.I)
    if m:
        return int(m.group(1))
    nums = re.findall(r"-?\d+", text)
    return int(nums[-1]) if nums else None


def _answer_tail_number(text: str) -> float | None:
    m = re.search(r"Answer:\s*(-?\d+(?:\.\d+)?)", text, re.I)
    if m:
        return float(m.group(1))
    nums = re.findall(r"-?\d+(?:\.\d+)?", text)
    return float(nums[-1]) if nums else None


def _parse_json_blob(text: str) -> Any:
    fence = re.search(r"```(?:json)?\n(.*?)```", text, re.S | re.I)
    raw = fence.group(1).strip() if fence else text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", raw, re.S)
        if not m:
            raise
        return json.loads(m.group(1))


def _tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = message.get("tool_calls") or []
    out = []
    for c in calls:
        fn = c.get("function") or {}
        args = fn.get("arguments") or "{}"
        if isinstance(args, str):
            try:
                args_obj = json.loads(args)
            except json.JSONDecodeError:
                args_obj = {}
        else:
            args_obj = args
        out.append({"name": fn.get("name"), "arguments": args_obj})
    return out


def score_response(
    *,
    checks: dict[str, Any] | None,
    content: str,
    message: dict[str, Any],
) -> dict[str, Any]:
    """Return {pass: bool, score: float, detail: str}."""
    if not checks:
        return {"pass": bool(content or message.get("tool_calls")), "score": 0.5, "detail": "no_checks"}

    ctype = checks.get("type")
    text = content or ""

    try:
        if ctype == "python_exec":
            code = _extract_code(text)
            got = _run_python(code, checks.get("setup") or "", checks["call"])
            expect = checks["expect"]
            # normalize list/tuple
            if isinstance(expect, list) and isinstance(got, tuple):
                got = list(got)
            ok = got == expect
            return {"pass": ok, "score": 1.0 if ok else 0.0, "detail": f"got={got!r}"}

        if ctype == "contains_all":
            ok = all(n.lower() in text.lower() for n in checks["needles"])
            return {"pass": ok, "score": 1.0 if ok else 0.0, "detail": "contains_all"}

        if ctype == "contains_any":
            ok = any(n.lower() in text.lower() for n in checks["needles"])
            return {"pass": ok, "score": 1.0 if ok else 0.0, "detail": "contains_any"}

        if ctype == "forbidden":
            bad = [f for f in checks["forbidden"] if f.lower() in text.lower()]
            ok = not bad
            return {"pass": ok, "score": 1.0 if ok else 0.0, "detail": f"forbidden={bad}"}

        if ctype == "answer_int":
            got = _answer_tail_int(text)
            ok = got == int(checks["expect"])
            return {"pass": ok, "score": 1.0 if ok else 0.0, "detail": f"got={got}"}

        if ctype == "answer_number":
            got = _answer_tail_number(text)
            tol = float(checks.get("tol") or 0.01)
            ok = got is not None and abs(got - float(checks["expect"])) <= tol
            return {"pass": ok, "score": 1.0 if ok else 0.0, "detail": f"got={got}"}

        if ctype == "tool_call":
            calls = _tool_calls(message)
            name = checks["name"]
            matched = [c for c in calls if c["name"] == name]
            if not matched:
                # sometimes models put call intent in content during dry-run
                return {"pass": False, "score": 0.0, "detail": f"no_tool:{name}"}
            args = matched[0]["arguments"]
            for k, v in (checks.get("args_contains") or {}).items():
                if str(v).lower() not in str(args.get(k, "")).lower() and str(v).lower() not in json.dumps(
                    args
                ).lower():
                    return {"pass": False, "score": 0.0, "detail": f"args_miss:{k}"}
            return {"pass": True, "score": 1.0, "detail": "tool_ok"}

        if ctype == "tool_call_any":
            calls = _tool_calls(message)
            names = {c["name"] for c in calls}
            ok = bool(names.intersection(set(checks["names"])))
            return {"pass": ok, "score": 1.0 if ok else 0.0, "detail": f"tools={names}"}

        if ctype == "json_obj":
            obj = _parse_json_blob(text)
            if not isinstance(obj, dict):
                return {"pass": False, "score": 0.0, "detail": "not_obj"}
            expect = checks["expect"]
            ok = all(obj.get(k) == v for k, v in expect.items())
            return {"pass": ok, "score": 1.0 if ok else 0.0, "detail": f"got={obj}"}

        if ctype == "json_list_contains":
            obj = _parse_json_blob(text)
            blob = json.dumps(obj).lower()
            ok = all(n.lower() in blob for n in checks["needles"])
            return {"pass": ok, "score": 1.0 if ok else 0.0, "detail": "list"}

        if ctype == "line_count":
            lines = [ln for ln in text.strip().splitlines() if ln.strip()]
            ok = checks["min_lines"] <= len(lines) <= checks["max_lines"]
            return {"pass": ok, "score": 1.0 if ok else 0.0, "detail": f"lines={len(lines)}"}

        if ctype == "max_words":
            words = re.findall(r"\w+", text)
            ok = len(words) <= int(checks["max_words"])
            if ok and checks.get("needles_any"):
                ok = any(n.lower() in text.lower() for n in checks["needles_any"])
            return {"pass": ok, "score": 1.0 if ok else 0.0, "detail": f"words={len(words)}"}

        if ctype == "summary_constraints":
            sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
            ok = len(sentences) <= int(checks.get("max_sentences") or 99)
            if ok and checks.get("needles_any"):
                ok = any(n.lower() in text.lower() for n in checks["needles_any"])
            return {"pass": ok, "score": 1.0 if ok else 0.0, "detail": f"sent={len(sentences)}"}

        return {"pass": False, "score": 0.0, "detail": f"unknown_check:{ctype}"}
    except Exception as exc:  # noqa: BLE001
        return {
            "pass": False,
            "score": 0.0,
            "detail": f"error:{exc.__class__.__name__}:{exc}",
            "trace": traceback.format_exc()[-400:],
        }


def soft_judge_needed(checks: dict[str, Any] | None) -> bool:
    """Whether an LLM judge should refine the score (open-ended creative/summary)."""
    if not checks:
        return True
    return checks.get("type") in {"summary_constraints", "line_count", "max_words", "forbidden"}
