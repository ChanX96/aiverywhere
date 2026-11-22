"""Single-instance resident supervisor for the loopback console and WeChat worker."""

from __future__ import annotations

import asyncio
import fcntl
import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import contextmanager

from . import channels
from ..integrations import wechat as legacy_wechat
from ..integrations.web.server import create_server
from .store import Store, atomic_write

_SPAWNED = []


def _reap(pid: int) -> None:
    """Reap a daemon that is still a direct child of this CLI/test process."""
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass


def _paths(store: Store):
    data = store.data
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    logs = data / "logs"
    logs.mkdir(mode=0o700, exist_ok=True)
    return {
        "info": data / "daemon.json",
        "runtime_lock": data / "daemon.lock",
        "startup_lock": data / "daemon.startup",
        "log": logs / "daemon.log",
    }


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _read_info(store: Store) -> dict | None:
    path = _paths(store)["info"]
    try:
        info = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if (not isinstance(info, dict) or type(info.get("pid")) is not int
            or not isinstance(info.get("token"), str)
            or not isinstance(info.get("port"), int)
            or info.get("home") != str(store.home)
            or info.get("project") != str(store.project)):
        return None
    if not _pid_alive(info["pid"]):
        path.unlink(missing_ok=True)
        return None
    return info


def _port_available(port: int) -> bool:
    if port == 0:
        return True
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _health(info: dict) -> bool:
    connection = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=1)
    try:
        connection.request("GET", "/api/health",
                           headers={"Host": f"127.0.0.1:{info['port']}"})
        response = connection.getresponse()
        payload = response.read(4096)
        return response.status == 200 and b'"ok"' in payload
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def status(store: Store) -> dict:
    info = _read_info(store)
    if info is None:
        return {"running": False}
    return {"running": _health(info), "pid": info["pid"], "port": info["port"],
            "url": f"http://127.0.0.1:{info['port']}/", "started": info.get("started"),
            "home": info.get("home"), "project": info.get("project")}


def _open(info: dict, mode: str) -> None:
    if mode == "never":
        return
    desktop = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if mode != "always" and not (
            sys.stdin.isatty() and sys.stdout.isatty()
            and (sys.platform == "darwin" or desktop)):
        return
    try:
        webbrowser.open(f"http://127.0.0.1:{info['port']}/")
    except (OSError, RuntimeError):
        pass


@contextmanager
def _startup_lock(store: Store):
    path = _paths(store)["startup_lock"]
    with path.open("a+b") as stream:
        os.fchmod(stream.fileno(), 0o600)
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def ensure(store: Store, *, port: int | None = None, open_browser: str = "never") -> dict:
    """Start one detached supervisor or attach to the existing instance."""
    info = _read_info(store)
    if info is not None and _health(info):
        _open(info, open_browser)
        return info
    with _startup_lock(store):
        info = _read_info(store)
        if info is not None and _health(info):
            _open(info, open_browser)
            return info
        if info is not None:
            raise RuntimeError(f"常驻进程 PID {info['pid']} 存在但 Web 健康检查失败")
        paths = _paths(store)
        paths["log"].touch(mode=0o600)
        log = paths["log"].open("ab")
        os.fchmod(log.fileno(), 0o600)
        desired = store.defaults()["port"] if port is None else port
        if not _port_available(desired):
            desired = 0
        child = subprocess.Popen(
            [sys.executable, "-m", "aiverywhere", "--home", str(store.home),
             "--project", str(store.project), "_daemon", "--port", str(desired)],
            cwd=store.project, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True, close_fds=True)
        _SPAWNED.append(child)
        log.close()
        deadline = time.time() + 30
        while time.time() < deadline:
            info = _read_info(store)
            if info is not None and _health(info):
                _open(info, open_browser)
                return info
            if child.poll() is not None:
                break
            time.sleep(0.1)
        try:
            child.terminate()
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
        tail = ""
        try:
            tail = paths["log"].read_text(errors="replace")[-3000:]
        except OSError:
            pass
        detail = f"exit={child.returncode}" if child.returncode is not None else "still running"
        raise RuntimeError("常驻进程启动失败（" + detail + "）" +
                           (f"：{tail.strip()}" if tail.strip() else "；日志为空，请检查 daemon 启动"))


def stop(store: Store) -> dict:
    info = _read_info(store)
    if info is None:
        return {"stopped": False, "reason": "not running"}
    try:
        os.kill(info["pid"], signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.time() + 10
    while time.time() < deadline and _pid_alive(info["pid"]):
        _reap(info["pid"])
        time.sleep(0.1)
    if _pid_alive(info["pid"]):
        try:
            os.kill(info["pid"], signal.SIGKILL)
        except ProcessLookupError:
            pass
    _paths(store)["info"].unlink(missing_ok=True)
    return {"stopped": True, "pid": info["pid"]}


def _channel_worker(store: Store, stopping: threading.Event) -> None:
    async def loop():
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            while not stopping.is_set():
                try:
                    key = channels.next_job(store)
                except (OSError, ValueError):
                    key = None
                if not key:
                    try:
                        key = legacy_wechat.next_job(store)
                    except (OSError, ValueError):
                        key = None
                if not key:
                    await asyncio.sleep(1)
                    continue
                try:
                    if key.startswith("wechat:"):
                        await legacy_wechat.process(store, client, key)
                    else:
                        await channels.process(store, client, key)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await asyncio.sleep(1)
    try:
        asyncio.run(loop())
    except Exception:
        return


def run_daemon(store: Store, port: int) -> int:
    paths = _paths(store)
    lock = paths["runtime_lock"].open("a+b")
    os.fchmod(lock.fileno(), 0o600)
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return 0
    server = None
    stopping = threading.Event()
    try:
        server = create_server(store, port)
        info = {"pid": os.getpid(), "port": server.server_port,
                "token": server.token, "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "home": str(store.home), "project": str(store.project)}
        atomic_write(paths["info"], (json.dumps(info, ensure_ascii=False) + "\n").encode(), mode=0o600)
        web = threading.Thread(target=server.serve_forever, name="aiverywhere-web", daemon=True)
        worker = threading.Thread(target=_channel_worker, args=(store, stopping),
                                  name="aiverywhere-channel", daemon=True)
        web.start()
        worker.start()

        def terminate(signum, frame):
            stopping.set()

        signal.signal(signal.SIGTERM, terminate)
        signal.signal(signal.SIGINT, terminate)
        while not stopping.wait(0.5):
            pass
        server.shutdown()
        server.server_close()
        web.join(timeout=5)
        worker.join(timeout=5)
        return 0
    finally:
        paths["info"].unlink(missing_ok=True)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        finally:
            lock.close()
