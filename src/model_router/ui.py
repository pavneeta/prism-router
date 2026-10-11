"""Interactive terminal getting-started UX — ``model-router ui``.

Stdlib REPL (stdin prompts). Does not start the gateway unless ``--start``.
Never prints secrets or remote hostnames.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from model_router.init_cmd import LOCAL_BASE, PLACEHOLDER_BASE
from model_router.why import explain_prompt, format_explain

DEFAULT_LISTEN = "http://127.0.0.1:4000"
_PROVIDER_ENV = (
    ("openai", ("OPENAI_API_KEY",)),
    ("anthropic", ("ANTHROPIC_API_KEY",)),
    ("fireworks", ("FIREWORKS_API_KEY", "FIREWORKS_AI_API_KEY")),
    ("together", ("TOGETHER_API_KEY",)),
)
_REPLY_EXCERPT = 400
_HEALTH_TIMEOUT = 0.6
_SEND_TIMEOUT = 45.0
_START_WAIT_SECONDS = 8.0

FetchJson = Callable[[str, float], tuple[int, Any] | None]


@dataclass(frozen=True)
class StatusReport:
    gateway_up: bool
    dry_run: bool
    providers: dict[str, bool]
    snapshot_date: str | None
    listen_url: str
    ready_status: str | None
    start_hint: str | None = None


def normalize_base(base: str | None) -> str:
    raw = (base or DEFAULT_LISTEN).strip()
    if not raw:
        raw = DEFAULT_LISTEN
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlparse(raw)
    host = parsed.hostname or "127.0.0.1"
    if host in {"0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    port = parsed.port or 4000
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")]
    return f"{parsed.scheme or 'http'}://{host}:{port}{path}"


def listen_url_from_settings() -> str:
    from model_router.config import get_settings

    settings = get_settings()
    host = settings.model_router_host
    if host in {"0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    return f"http://{host}:{settings.model_router_port}"


def provider_key_flags(environ: dict[str, str] | None = None) -> dict[str, bool]:
    env = os.environ if environ is None else environ
    flags: dict[str, bool] = {}
    for name, keys in _PROVIDER_ENV:
        flags[name] = any(bool((env.get(key) or "").strip()) for key in keys)
    return flags


def bool_providers(raw: Any) -> dict[str, bool]:
    if not isinstance(raw, dict):
        return {}
    return {str(key): bool(value) for key, value in raw.items()}


def fetch_json(url: str, timeout: float = _HEALTH_TIMEOUT) -> tuple[int, Any] | None:
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            payload: Any = json.loads(raw) if raw else {}
            return int(resp.status), payload
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        return int(exc.code), payload
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def post_json(
    url: str,
    body: dict[str, Any],
    *,
    timeout: float = _SEND_TIMEOUT,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any] | None:
    data = json.dumps(body).encode("utf-8")
    req_headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            payload: Any = json.loads(raw) if raw else {}
            return int(resp.status), payload
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"error": raw.decode("utf-8", errors="replace")}
        return int(exc.code), payload
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def _client_auth_headers() -> dict[str, str]:
    raw = (os.getenv("MODEL_ROUTER_API_KEYS") or "").strip()
    if not raw:
        return {}
    key = raw.split(",", 1)[0].strip()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


def collect_status(
    *,
    base: str | None = None,
    fetch: FetchJson | None = None,
) -> StatusReport:
    from model_router.config import get_settings, load_benchmarks

    settings = get_settings()
    listen = normalize_base(base) if base else listen_url_from_settings()
    snapshot_date: str | None = None
    try:
        snapshot_date = load_benchmarks().snapshot_date
    except Exception:  # noqa: BLE001 — status must still print
        snapshot_date = None

    getter = fetch or fetch_json
    health = getter(f"{listen}/health", _HEALTH_TIMEOUT)
    ready = getter(f"{listen}/ready", _HEALTH_TIMEOUT) if health else None

    local_providers = provider_key_flags()
    dry_run = bool(settings.model_router_dry_run)
    gateway_up = False
    ready_status: str | None = None
    if health is not None:
        status_code, payload = health
        if status_code == 200 and isinstance(payload, dict) and payload.get("status") == "ok":
            gateway_up = True
            dry_run = bool(payload.get("dry_run", dry_run))
            probed = bool_providers(payload.get("providers"))
            if probed:
                local_providers = probed
    if ready is not None and isinstance(ready[1], dict):
        ready_status = str(ready[1].get("status") or ready[0])

    hint = None
    if not gateway_up:
        hint = (
            "Gateway is not running. Start it in another terminal:\n"
            "\n"
            "  model-router\n"
        )
    return StatusReport(
        gateway_up=gateway_up,
        dry_run=dry_run,
        providers=local_providers,
        snapshot_date=snapshot_date,
        listen_url=listen,
        ready_status=ready_status,
        start_hint=hint,
    )


def format_status(report: StatusReport) -> str:
    providers = "  ".join(
        f"{name}={'true' if present else 'false'}"
        for name, present in report.providers.items()
    )
    lines = [
        f"gateway:    {'up' if report.gateway_up else 'down'}",
        f"listen:     {report.listen_url}",
        f"dry_run:    {'true' if report.dry_run else 'false'}",
        f"snapshot:   {report.snapshot_date or 'unknown'}",
        f"providers:  {providers or '(none)'}",
    ]
    if report.ready_status:
        lines.insert(2, f"ready:      {report.ready_status}")
    if report.start_hint:
        lines.extend(["", report.start_hint.rstrip()])
    return "\n".join(lines)


def format_setup(listen_url: str | None = None) -> str:
    listen = listen_url or listen_url_from_settings()
    local_v1 = f"{listen.rstrip('/')}/v1"
    return "\n".join(
        [
            "Point an OpenAI-compatible client at this machine:",
            "",
            f'  export OPENAI_API_BASE="{local_v1}"',
            f'  # self-hosted: export OPENAI_API_BASE="{PLACEHOLDER_BASE}"',
            "",
            "Write harness presets (does not start the gateway):",
            "",
            "  model-router init opencode",
            "  model-router init cursor",
            "  model-router init hermes",
            "",
            "Start the gateway in another terminal, then send traffic:",
            "",
            "  model-router",
            f"  # local example: {LOCAL_BASE}",
        ]
    )


def _excerpt(text: str, limit: int = _REPLY_EXCERPT) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def format_send(
    *,
    via: str,
    classification_task: str | None,
    model: str | None,
    estimated_cost_usd: float | None,
    reply: str | None,
    note: str | None = None,
) -> str:
    cost = (
        f"{estimated_cost_usd:.6f}"
        if isinstance(estimated_cost_usd, (int, float))
        else "n/a"
    )
    lines = [
        f"task:       {classification_task or 'n/a'}",
        f"model:      {model or 'n/a'}",
        f"est $:      {cost}",
        f"via:        {via}",
    ]
    if reply:
        lines.extend(["", _excerpt(reply)])
    if note:
        lines.extend(["", note])
    return "\n".join(lines)


def send_prompt(
    prompt: str,
    *,
    base: str | None = None,
    fetch_post: Callable[..., tuple[int, Any] | None] | None = None,
) -> str:
    listen = normalize_base(base) if base else listen_url_from_settings()
    poster = fetch_post or post_json
    result = poster(
        f"{listen}/v1/chat/completions",
        {
            "model": "auto",
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=_SEND_TIMEOUT,
        headers=_client_auth_headers() or None,
    )
    if result is not None:
        status_code, payload = result
        if status_code == 200 and isinstance(payload, dict):
            meta = payload.get("model_router") if isinstance(payload.get("model_router"), dict) else {}
            decision = meta.get("decision") if isinstance(meta.get("decision"), dict) else {}
            classification = (
                meta.get("classification") if isinstance(meta.get("classification"), dict) else {}
            )
            choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
            content = None
            if choices and isinstance(choices[0], dict):
                message = choices[0].get("message")
                if isinstance(message, dict):
                    content = message.get("content")
            return format_send(
                via="gateway",
                classification_task=classification.get("task_type") if classification else None,
                model=decision.get("selected_model") or payload.get("model"),
                estimated_cost_usd=decision.get("estimated_cost_usd"),
                reply=str(content) if content is not None else None,
            )
        err = payload.get("error") if isinstance(payload, dict) else payload
        if isinstance(err, dict):
            err = err.get("message") or err.get("code") or err
        return format_send(
            via="gateway",
            classification_task=None,
            model=None,
            estimated_cost_usd=None,
            reply=None,
            note=f"gateway returned HTTP {status_code}: {err}",
        )

    classification, decision = explain_prompt(prompt)
    return format_send(
        via="in-process (gateway not running)",
        classification_task=classification.task_type,
        model=decision.selected_model,
        estimated_cost_usd=decision.estimated_cost_usd,
        reply=(
            f"[dry-run] would route to {decision.selected_model} "
            f"for task={classification.task_type}"
        ),
        note="Start `model-router` in another terminal to send a live request.",
    )


def _why(prompt: str) -> str:
    classification, decision = explain_prompt(prompt)
    return format_explain(classification, decision)


def _read_prompt(existing: str | None, label: str) -> str | None:
    if existing and existing.strip():
        return existing.strip()
    try:
        typed = input(f"{label}: ").strip()
    except EOFError:
        return None
    return typed or None


def format_repl_help() -> str:
    return "\n".join(
        [
            "status   gateway health or local settings",
            "why      classify + route a prompt (no server required)",
            "send     POST /v1/chat/completions (or in-process dry-run)",
            "setup    OPENAI_API_BASE + model-router init hints",
            "quit     exit",
        ]
    )


def run_repl(*, base: str | None = None) -> int:
    print("Prism Router — local getting-started CLI")
    print("status  why  send  setup  quit   (help for details)")
    print()
    while True:
        try:
            line = input("prism> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        command, _, rest = line.partition(" ")
        command = command.lower()
        rest = rest.strip()
        if command in {"quit", "q", "exit"}:
            return 0
        if command in {"help", "h", "?"}:
            print(format_repl_help())
            continue
        if command in {"status", "s"}:
            print(format_status(collect_status(base=base)))
            continue
        if command in {"why", "w"}:
            prompt = _read_prompt(rest, "prompt")
            if not prompt:
                print("prompt required")
                continue
            print(_why(prompt))
            continue
        if command == "send":
            prompt = _read_prompt(rest, "prompt")
            if not prompt:
                print("prompt required")
                continue
            print(send_prompt(prompt, base=base))
            continue
        if command == "setup":
            print(format_setup(normalize_base(base) if base else None))
            continue
        print(f"unknown command: {command}  (try help)")
    return 0


def _parse_host_port(base: str) -> tuple[str, int]:
    parsed = urlparse(normalize_base(base))
    return parsed.hostname or "127.0.0.1", parsed.port or 4000


def start_gateway(
    base: str,
    *,
    popen: Callable[..., subprocess.Popen[Any]] | None = None,
    wait_health: FetchJson | None = None,
    wait_seconds: float = _START_WAIT_SECONDS,
) -> subprocess.Popen[Any] | None:
    """Spawn a local gateway only when ``--start`` is set and nothing is listening."""
    listen = normalize_base(base)
    getter = wait_health or fetch_json
    if getter(f"{listen}/health", _HEALTH_TIMEOUT) is not None:
        print(f"gateway already running at {listen}", file=sys.stderr)
        return None
    host, port = _parse_host_port(listen)
    launcher = popen or subprocess.Popen
    proc = launcher(
        [sys.executable, "-m", "model_router", "--host", host, "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            print("failed to start gateway (`model-router --start`)", file=sys.stderr)
            return proc
        if getter(f"{listen}/health", _HEALTH_TIMEOUT) is not None:
            print(f"started gateway at {listen}", file=sys.stderr)
            return proc
        time.sleep(0.15)
    print(
        f"gateway at {listen} did not become ready; continuing without it",
        file=sys.stderr,
    )
    return proc


def stop_gateway(proc: subprocess.Popen[Any] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="model-router ui",
        description=(
            "Interactive local getting-started CLI. "
            "Does not start the gateway unless --start is passed."
        ),
    )
    ap.add_argument(
        "--status",
        action="store_true",
        help="Print gateway / local settings and exit",
    )
    ap.add_argument(
        "--why",
        metavar="PROMPT",
        help="Explain classification + selected model and exit",
    )
    ap.add_argument(
        "--send",
        metavar="PROMPT",
        help="POST chat completions to the local gateway (or in-process dry-run)",
    )
    ap.add_argument(
        "--setup",
        action="store_true",
        help="Print OPENAI_API_BASE and init hints and exit",
    )
    ap.add_argument(
        "--start",
        action="store_true",
        help="Start a local gateway for this session (stopped on exit)",
    )
    ap.add_argument(
        "--base",
        default=None,
        help=f"Gateway URL (default {DEFAULT_LISTEN})",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base = args.base
    proc = None
    try:
        if args.start:
            target = normalize_base(base) if base else listen_url_from_settings()
            proc = start_gateway(target)
        oneshot = args.status or args.why is not None or args.send is not None or args.setup
        if args.status:
            print(format_status(collect_status(base=base)))
        if args.why is not None:
            if not str(args.why).strip():
                print("prompt required for --why", file=sys.stderr)
                return 2
            print(_why(args.why))
        if args.send is not None:
            if not str(args.send).strip():
                print("prompt required for --send", file=sys.stderr)
                return 2
            print(send_prompt(args.send, base=base))
        if args.setup:
            print(format_setup(normalize_base(base) if base else None))
        if oneshot:
            return 0
        return run_repl(base=base)
    except KeyboardInterrupt:
        print()
        return 0
    finally:
        stop_gateway(proc)


if __name__ == "__main__":
    raise SystemExit(main())
