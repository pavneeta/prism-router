"""Background gateway process — PID file, log file, start / stop / status.

State lives under ``~/.prism-router`` (override with ``PRISM_ROUTER_HOME``).
The daemon refuses to double-bind if a healthy gateway is already listening
on the requested URL, and ``stop`` will not kill a process it does not own.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

ENV_HOME = "PRISM_ROUTER_HOME"
ENV_HOME_ALIASES = (ENV_HOME, "MODEL_ROUTER_HOME")
DEFAULT_HOME_NAME = ".prism-router"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4000
_HEALTH_TIMEOUT = 0.6
_OWN_MARKERS = ("model_router", "model-router")

HealthFn = Callable[[str, int], bool]
AliveFn = Callable[[int], bool]
PopenFn = Callable[..., Any]


class DaemonError(RuntimeError):
    """Could not start or stop the background gateway."""


@dataclass(frozen=True)
class DaemonState:
    running: bool
    pid: int | None
    host: str
    port: int
    url: str
    log_path: Path
    pid_path: Path
    already_running: bool = False
    started: bool = False
    owned: bool = False
    message: str = ""


def resolve_home(home: Path | str | None = None) -> Path:
    if home:
        return Path(home).expanduser().resolve()
    for key in ENV_HOME_ALIASES:
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
    return Path.home() / DEFAULT_HOME_NAME


def listen_url(host: str, port: int) -> str:
    display = "127.0.0.1" if host in {"0.0.0.0", "::", "[::]"} else host
    return f"http://{display}:{int(port)}"


def pid_path(home: Path | str | None = None) -> Path:
    return resolve_home(home) / "gateway.pid"


def log_path(home: Path | str | None = None) -> Path:
    return resolve_home(home) / "gateway.log"


def meta_path(home: Path | str | None = None) -> Path:
    return resolve_home(home) / "gateway.json"


def _ensure_home(home: Path) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    return home


def _read_pid(home: Path) -> int | None:
    path = pid_path(home)
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip().splitlines()[0]
        pid = int(raw)
    except (OSError, ValueError, IndexError):
        return None
    return pid if pid > 0 else None


def _read_meta(home: Path) -> dict[str, Any]:
    path = meta_path(home)
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_state(home: Path, pid: int, host: str, port: int) -> None:
    _ensure_home(home)
    pid_path(home).write_text(f"{pid}\n", encoding="utf-8")
    meta_path(home).write_text(
        json.dumps({"pid": pid, "host": host, "port": port}, indent=2) + "\n",
        encoding="utf-8",
    )


def _clear_state(home: Path) -> None:
    for path in (pid_path(home), meta_path(home)):
        try:
            path.unlink()
        except OSError:
            pass


def pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _command_line(pid: int) -> str:
    try:
        proc = Path(f"/proc/{pid}/cmdline")
        if proc.is_file():
            return proc.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace")
        out = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "command="],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def pid_is_ours(pid: int, *, is_alive: AliveFn = pid_is_alive) -> bool:
    if not is_alive(pid):
        return False
    cmdline = _command_line(pid)
    if not cmdline:
        return True
    return any(marker in cmdline for marker in _OWN_MARKERS)


def port_is_open(host: str, port: int) -> bool:
    probe = "127.0.0.1" if host in {"0.0.0.0", "::", "[::]"} else host
    try:
        with socket.create_connection((probe, int(port)), timeout=0.4):
            return True
    except OSError:
        return False


def health_ok(host: str, port: int) -> bool:
    url = f"{listen_url(host, port)}/health"
    req = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(req, timeout=_HEALTH_TIMEOUT) as resp:
            if int(resp.status) != 200:
                return False
            payload = json.loads(resp.read() or b"{}")
    except (URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("status") == "ok"


def ready_status(host: str, port: int) -> str | None:
    url = f"{listen_url(host, port)}/ready"
    req = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(req, timeout=_HEALTH_TIMEOUT) as resp:
            payload = json.loads(resp.read() or b"{}")
    except (URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return None
    if isinstance(payload, dict) and payload.get("status"):
        return str(payload["status"])
    return None


def _stop_pid(
    pid: int,
    timeout: float = 8.0,
    *,
    is_alive: AliveFn = pid_is_alive,
    send_signal: Callable[[int, int], None] | None = None,
) -> None:
    send = send_signal or os.kill
    if not is_alive(pid):
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        try:
            send(pid, signal.SIGTERM)
        except OSError:
            return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_alive(pid):
            return
        time.sleep(0.05)
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        try:
            send(pid, signal.SIGKILL)
        except OSError:
            pass


def inspect(
    *,
    host: str | None = None,
    port: int | None = None,
    home: Path | str | None = None,
    health: HealthFn | None = None,
    is_alive: AliveFn | None = None,
) -> DaemonState:
    root = resolve_home(home)
    meta = _read_meta(root)
    pid = _read_pid(root)
    explicit = host is not None or port is not None
    has_state = bool(meta or pid)
    use_host = host or str(meta.get("host") or DEFAULT_HOST)
    use_port = int(port if port is not None else (meta.get("port") or DEFAULT_PORT))
    check_health = health or health_ok
    check_alive = is_alive or pid_is_alive
    owned = bool(pid and pid_is_ours(pid, is_alive=check_alive))
    if pid is not None and not owned:
        pid = None
    # Empty home + default 4000 must not claim a foreign listener as this daemon.
    healthy = check_health(use_host, use_port) if (explicit or has_state) else False
    live_pid = pid if pid and check_alive(pid) else None
    running = bool(live_pid or healthy)
    return DaemonState(
        running=running,
        pid=live_pid,
        host=use_host,
        port=use_port,
        url=listen_url(use_host, use_port),
        log_path=log_path(root),
        pid_path=pid_path(root),
        already_running=running,
        owned=bool(live_pid),
        message="up" if running else "down",
    )


def start_daemon(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    home: Path | str | None = None,
    wait_seconds: float = 20.0,
    extra_args: list[str] | None = None,
    popen: PopenFn | None = None,
    health: HealthFn | None = None,
    port_open: Callable[[str, int], bool] | None = None,
    is_alive: AliveFn | None = None,
) -> DaemonState:
    """Start a detached gateway, or return the already-running one."""
    root = resolve_home(home)
    check_health = health or health_ok
    check_port = port_open or port_is_open
    check_alive = is_alive or pid_is_alive
    current = inspect(host=host, port=port, home=root, health=check_health, is_alive=check_alive)
    if current.running and check_health(host, port):
        return DaemonState(
            running=True,
            pid=current.pid,
            host=host,
            port=port,
            url=listen_url(host, port),
            log_path=log_path(root),
            pid_path=pid_path(root),
            already_running=True,
            started=False,
            owned=current.owned,
            message=f"already running at {listen_url(host, port)}",
        )
    if check_port(host, port) and not check_health(host, port):
        raise DaemonError(
            f"{host}:{port} is in use by another process; choose a different port"
        )
    if current.pid and not check_alive(current.pid):
        _clear_state(root)

    _ensure_home(root)
    log = log_path(root)
    log_file = log.open("a", encoding="utf-8")
    cmd = [
        sys.executable,
        "-m",
        "model_router",
        "serve",
        "--host",
        host,
        "--port",
        str(port),
        *(extra_args or []),
    ]
    launcher = popen or subprocess.Popen
    try:
        proc = launcher(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_file.close()

    _write_state(root, int(proc.pid), host, port)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            _clear_state(root)
            raise DaemonError(
                f"gateway exited before it was ready (pid {proc.pid}); see {log}"
            )
        if check_health(host, port):
            return DaemonState(
                running=True,
                pid=int(proc.pid),
                host=host,
                port=port,
                url=listen_url(host, port),
                log_path=log,
                pid_path=pid_path(root),
                already_running=False,
                started=True,
                owned=True,
                message=f"listening on {listen_url(host, port)}",
            )
        time.sleep(0.05)

    _stop_pid(int(proc.pid), is_alive=check_alive)
    _clear_state(root)
    raise DaemonError(f"gateway at {listen_url(host, port)} did not become ready; see {log}")


def stop_daemon(
    *,
    home: Path | str | None = None,
    timeout: float = 8.0,
    health: HealthFn | None = None,
    is_alive: AliveFn | None = None,
    send_signal: Callable[[int, int], None] | None = None,
) -> DaemonState:
    root = resolve_home(home)
    check_health = health or health_ok
    check_alive = is_alive or pid_is_alive
    current = inspect(home=root, health=check_health, is_alive=check_alive)
    pid = current.pid
    if pid and current.owned:
        _stop_pid(pid, timeout=timeout, is_alive=check_alive, send_signal=send_signal)
    elif current.running and current.pid is None:
        return DaemonState(
            running=True,
            pid=None,
            host=current.host,
            port=current.port,
            url=current.url,
            log_path=current.log_path,
            pid_path=current.pid_path,
            already_running=True,
            owned=False,
            message=f"a gateway is listening at {current.url} but is not this daemon",
        )
    _clear_state(root)
    still = check_health(current.host, current.port)
    return DaemonState(
        running=still,
        pid=None,
        host=current.host,
        port=current.port,
        url=current.url,
        log_path=current.log_path,
        pid_path=current.pid_path,
        already_running=False,
        owned=False,
        message="stopped" if not still else f"still listening at {current.url}",
    )


def format_status(state: DaemonState) -> str:
    lines = [
        f"gateway:    {'up' if state.running else 'down'}",
        f"listen:     {state.url}",
        f"pid:        {state.pid if state.pid else '-'}",
        f"log:        {state.log_path}",
    ]
    if state.message and state.message not in {"up", "down"}:
        lines.append(f"note:       {state.message}")
    return "\n".join(lines)


def _home_arg(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--home",
        default=None,
        help=f"State directory (default ${ENV_HOME} or ~/{DEFAULT_HOME_NAME})",
    )


def status_main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="model-router status",
        description="Show whether the background Prism gateway is running.",
    )
    _home_arg(ap)
    args = ap.parse_args(argv)
    print(format_status(inspect(home=args.home)))
    return 0


def stop_main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="model-router stop",
        description="Stop the background Prism gateway started by `model-router init`.",
    )
    _home_arg(ap)
    args = ap.parse_args(argv)
    state = stop_daemon(home=args.home)
    print(format_status(state))
    if state.message == "stopped":
        print("stopped")
    return 0 if not state.running else 1
