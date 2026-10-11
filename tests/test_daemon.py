from __future__ import annotations

import signal
import socket
from pathlib import Path

from model_router.cli import main as cli_main
from model_router.daemon import (
    ENV_HOME,
    inspect,
    start_daemon,
    stop_daemon,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _repo_config() -> Path:
    return Path(__file__).resolve().parents[1] / "config"


class _FakeProc:
    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self._alive = True

    def poll(self) -> int | None:
        return None if self._alive else 0


def test_status_and_stop_when_idle(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setenv(ENV_HOME, str(tmp_path))
    monkeypatch.setattr("model_router.daemon.health_ok", lambda host, port: False)
    assert cli_main(["status"]) == 0
    out = capsys.readouterr().out
    assert "down" in out
    assert str(tmp_path / "gateway.log") in out
    assert cli_main(["stop"]) == 0
    assert "down" in capsys.readouterr().out


def test_start_skips_when_health_already_up(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(ENV_HOME, str(tmp_path))
    spawned: list[object] = []

    def fake_popen(*args, **kwargs):
        spawned.append(args)
        raise AssertionError("should not spawn when health is up")

    state = start_daemon(
        "127.0.0.1",
        4123,
        home=tmp_path,
        popen=fake_popen,
        health=lambda host, port: True,
        port_open=lambda host, port: True,
        wait_seconds=0.2,
    )
    assert state.running is True
    assert state.already_running is True
    assert state.started is False
    assert spawned == []
    assert "already running" in state.message


def test_start_writes_pid_and_stop_signals(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(ENV_HOME, str(tmp_path))
    proc = _FakeProc()
    spawned: list[list[str]] = []
    signals: list[int] = []
    healthy = {"value": False}

    def fake_popen(cmd, **kwargs):
        spawned.append(list(cmd))
        healthy["value"] = True
        return proc

    def fake_health(host: str, port: int) -> bool:
        return healthy["value"]

    def fake_alive(pid: int) -> bool:
        return pid == proc.pid and proc._alive and signal.SIGKILL not in signals

    def fake_signal(pid: int, sig: int) -> None:
        signals.append(sig)
        if sig in {signal.SIGTERM, signal.SIGKILL}:
            proc._alive = False
            healthy["value"] = False

    state = start_daemon(
        "127.0.0.1",
        4123,
        home=tmp_path,
        popen=fake_popen,
        health=fake_health,
        port_open=lambda host, port: False,
        is_alive=fake_alive,
        wait_seconds=1,
    )
    assert state.started is True
    assert state.pid == 4242
    assert (tmp_path / "gateway.pid").read_text(encoding="utf-8").strip() == "4242"
    assert (tmp_path / "gateway.json").is_file()
    assert "model_router" in spawned[0]

    again = start_daemon(
        "127.0.0.1",
        4123,
        home=tmp_path,
        popen=fake_popen,
        health=fake_health,
        port_open=lambda host, port: True,
        is_alive=fake_alive,
    )
    assert again.already_running is True
    assert len(spawned) == 1

    probed = inspect(
        host="127.0.0.1",
        port=4123,
        home=tmp_path,
        health=fake_health,
        is_alive=fake_alive,
    )
    assert probed.running is True
    assert probed.pid == 4242

    stopped = stop_daemon(
        home=tmp_path,
        health=fake_health,
        is_alive=fake_alive,
        send_signal=fake_signal,
    )
    assert stopped.running is False
    assert stopped.message == "stopped"
    assert signal.SIGTERM in signals
    assert not (tmp_path / "gateway.pid").exists()


def test_stop_does_not_kill_foreign_listener(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(ENV_HOME, str(tmp_path))
    (tmp_path / "gateway.json").write_text(
        '{"host": "127.0.0.1", "port": 4123}\n',
        encoding="utf-8",
    )
    signals: list[int] = []
    state = stop_daemon(
        home=tmp_path,
        health=lambda host, port: True,
        is_alive=lambda pid: False,
        send_signal=lambda pid, sig: signals.append(sig),
    )
    assert state.running is True
    assert signals == []
    assert "not this daemon" in state.message


def test_cli_status_uses_home(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setenv(ENV_HOME, str(tmp_path))
    (tmp_path / "gateway.json").write_text(
        '{"pid": 1, "host": "127.0.0.1", "port": 4123}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("model_router.daemon.health_ok", lambda host, port: False)
    monkeypatch.setattr("model_router.daemon.pid_is_ours", lambda pid, is_alive=None: False)
    assert cli_main(["status"]) == 0
    out = capsys.readouterr().out
    assert "127.0.0.1:4123" in out
    assert "down" in out


def test_daemon_start_stop_throwaway_port(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(ENV_HOME, str(tmp_path))
    monkeypatch.setenv("MODEL_ROUTER_DRY_RUN", "true")
    monkeypatch.setenv("MODEL_ROUTER_CONFIG_DIR", str(_repo_config()))
    port = _free_port()
    state = start_daemon("127.0.0.1", port, home=tmp_path, wait_seconds=30)
    try:
        assert state.running is True
        assert state.pid is not None
        assert state.already_running is False
        assert (tmp_path / "gateway.pid").is_file()
        assert (tmp_path / "gateway.log").is_file()
        again = start_daemon("127.0.0.1", port, home=tmp_path, wait_seconds=5)
        assert again.already_running is True
        assert again.pid == state.pid
        probed = inspect(host="127.0.0.1", port=port, home=tmp_path)
        assert probed.running is True
        assert probed.pid == state.pid
    finally:
        stopped = stop_daemon(home=tmp_path)
    assert stopped.running is False
    assert inspect(host="127.0.0.1", port=port, home=tmp_path).running is False
