"""Loopback-only console. Mutations use the same store lock and revisions as the CLI."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

from ...core.session import SessionStore
from ...core.store import RevisionConflict, Store, file_version, skill_revision, skill_text
from .chat import ChatSessions
from ..bridges.registry import discover as discover_bridges


def log_page(store: Store, before: int | None = None, limit: int = 50) -> dict:
    """Page backwards by byte offset, even when other projects share the log."""
    rows = []
    try:
        stream = store.local("events.jsonl").open("rb")
    except FileNotFoundError:
        return {"rows": rows, "before": None}
    with stream:
        size = stream.seek(0, 2)
        cursor = end = size if before is None else min(size, max(0, before))
        fragment = b""
        while cursor:
            start = max(0, cursor - 8192)
            stream.seek(start)
            lines = (stream.read(cursor - start) + fragment).splitlines(keepends=True)
            fragment = lines.pop(0) if start else b""
            for line in reversed(lines):
                end -= len(line)
                try:
                    event = json.loads(line)
                except (UnicodeDecodeError, ValueError):
                    continue
                if isinstance(event, dict) and event.get("project") == str(store.project):
                    rows.append({k: event.get(k) for k in ("task_id", "run_id", "time", "status", "tool_calls")})
                    if len(rows) == limit:
                        return {"rows": rows, "before": end or None}
            cursor = start
    return {"rows": rows, "before": None}


def overview(store: Store) -> dict:
    items = store.memory_items()
    items.sort(key=lambda item: item["updated"], reverse=True)
    text = skill_text(store.home)
    try:
        model = store.configuration().get("model", {})
    except (OSError, ValueError):
        model = {}
    return {"project": str(store.project), "directory": str(store.data), "memory": items,
            "bridges": discover_bridges(store, check_health=True),
            "model": {"name": model.get("model"), "base_url": model.get("base_url"),
                      "max_tokens": model.get("max_tokens"), "configured": bool(model),
                      "executor": "native" if "command" in model else "messages"},
            "agent": {"path": str(store.agent_file), "text": text,
                      "revision": skill_revision(text), "local": store.agent_file.is_file(),
                      "files": store.agent_files()},
            "logs": log_page(store),
            "sessions": SessionStore(store).list()[:50]}


ASSETS = {"/": ("index.html", "text/html"), "/app.css": ("app.css", "text/css"),
          "/app.js": ("app.js", "text/javascript")}
ENTRY_PATH = re.compile(r"/api/memory/([0-9a-f]{32})")
SESSION_PATH = re.compile(r"/api/sessions/([0-9a-f]{32})\Z")
RUN_PATH = re.compile(r"/api/runs/([A-Za-z0-9_-]{1,200})\Z")
CHANNEL_PATH = re.compile(r"/api/channels/([A-Za-z0-9_-]{1,64})/(messages|status)\Z")


def create_server(store: Store, port: int, token: str | None = None) -> ThreadingHTTPServer:
    if not 0 <= port <= 65535:
        raise ValueError("端口须在 0–65535 之间")
    token = token or secrets.token_urlsafe(32)
    assets = files("aiverywhere.integrations.web").joinpath("static")
    chat = ChatSessions(store)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Browsing the console does not generate agent activity records.

        def reply(self, status, body, mime="application/json", *, etag=None):
            if mime == "application/json":
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if etag:
                self.send_header("ETag", etag)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def body(self):
            if self.headers.get_content_type() != "application/json":
                raise ValueError("请求需要 JSON")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 500_000:
                raise ValueError("请求长度无效")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("请求需要 JSON 对象")
            return data

        def dispatch(self):
            host = self.headers.get("Host", "")
            hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if host not in hosts or self.headers.get("Origin", "http://" + host) != "http://" + host:
                raise PermissionError("仅接受本机同源请求")
            target = urlsplit(self.path)
            path = target.path
            read = self.command in {"GET", "HEAD"}
            if read and path == "/api/health":
                return self.reply(200, {"ok": True, "pid": os.getpid()})
            if path in ASSETS and read:
                name, mime = ASSETS[path]
                raw = assets.joinpath(name).read_bytes()
                if path == "/":
                    raw = raw.replace(b"__SESSION_TOKEN__", token.encode())
                return self.reply(200, raw, mime)
            if not secrets.compare_digest(self.headers.get("X-Aiverywhere-Token", ""), token):
                raise PermissionError("请刷新本地页面以继续")
            channel_match = CHANNEL_PATH.fullmatch(path)
            if channel_match and channel_match[2] == "messages" and self.command == "POST":
                from ...core import channels
                data = self.body()
                data["channel"] = channel_match[1]
                return self.reply(202, channels.receive(store, data, channel_match[1]))
            if channel_match and channel_match[2] == "status" and read:
                from ...core import channels
                ident = parse_qs(target.query).get("task_id", [""])[0]
                return self.reply(200, channels.status(store, ident))
            if path == "/api/wechat" and self.command == "POST":
                from ...core import channels
                data = self.body()
                data["channel"] = "wechat"
                return self.reply(202, channels.receive(store, data, "wechat"))
            if read and path == "/api/wechat/status":
                from ...core import channels
                ident = parse_qs(target.query).get("task_id", [""])[0]
                return self.reply(200, channels.status(store, ident))
            if read and path == "/api/workspace":
                # When idle, a tab only checks file metadata. The tag is captured
                # before reading so a concurrent write is picked up by the next poll.
                agent = file_version(store.agent_file) or skill_revision(skill_text(store.home))
                bundle = hashlib.sha256(repr(
                    [(item["path"], item["sha256"]) for item in store.agent_files()]).encode()).hexdigest()
                sessions = hashlib.sha256(repr(
                    [(item["id"], item["updated"], item["turns"])
                     for item in SessionStore(store).list()]).encode()).hexdigest()
                bridges = hashlib.sha256(repr(
                    [(item["id"], item["path"], item["enabled"])
                     for item in discover_bridges(store)]).encode()).hexdigest()
                versions = (agent, bundle, sessions, bridges, file_version(store.path),
                            file_version(store.local("events.jsonl")),
                            file_version(store.config_path), store.memory.fingerprint())
                tag = '"' + hashlib.sha256(repr(versions).encode()).hexdigest() + '"'
                if self.headers.get("If-None-Match") == tag:
                    self.send_response(304)
                    self.send_header("ETag", tag)
                    self.end_headers()
                    return
                return self.reply(200, overview(store), etag=tag)
            if path == "/api/chat":
                if read:
                    session = parse_qs(target.query).get("session", [""])[0]
                    return self.reply(200, chat.state(session))
                if self.command != "POST":
                    return self.reply(405, {"error": "不支持该请求"})
                data = self.body()
                return self.reply(202, chat.start(data.get("session"), data.get("message"),
                                                  data.get("writable", False),
                                                  data.get("exec", False),
                                                  data.get("network", True)))
            if path == "/api/chat/reset" and self.command == "POST":
                data = self.body()
                return self.reply(200, chat.reset(data.get("session")))
            if read and RUN_PATH.fullmatch(path):
                run_id = RUN_PATH.fullmatch(path)[1]
                try:
                    return self.reply(200, store.run_detail(run_id))
                except (OSError, ValueError) as exc:
                    return self.reply(404, {"error": str(exc)})
            if read and path == "/api/sessions":
                return self.reply(200, {"sessions": SessionStore(store).list()})
            if read and SESSION_PATH.fullmatch(path):
                ident = SESSION_PATH.fullmatch(path)[1]
                try:
                    session = SessionStore(store).open(ident)
                    session.load()
                except (OSError, ValueError) as exc:
                    return self.reply(404, {"error": str(exc)})
                return self.reply(200, session.info() | {
                    "history": session.history()[-100:],
                    "summary": session.summary()})
            if path == "/api/logs":
                if not read:
                    return self.reply(405, {"error": "运行日志只读"})
                before = parse_qs(target.query).get("before", [None])[0]
                return self.reply(200, log_page(store, None if before is None else int(before)))
            match = ENTRY_PATH.fullmatch(path)
            if read and match:
                try:
                    item = store.recall(match[1])
                except ValueError:
                    return self.reply(404, {"error": "本项目没有该条目"})
                return self.reply(200, {k: item[k] for k in ("id", "kind", "title", "text", "revision")})
            if read and path == "/api/agent/file":
                relative = parse_qs(target.query).get("path", [""])[0]
                return self.reply(200, store.read_agent_file(relative))
            if path == "/api/agent/file" and self.command == "PUT":
                data = self.body()
                if not all(isinstance(data.get(k), str) for k in ("path", "text", "revision")):
                    raise ValueError("agent 文件需要 path、text 和 revision")
                return self.reply(200, store.write_agent_file(
                    data["path"], data["text"], data["revision"]))
            if path == "/api/agent" and self.command in {"PUT", "DELETE"}:
                data = self.body()
                revision = data.get("revision")
                if not isinstance(revision, str):
                    raise ValueError("缺少 agent 修订号")
                if self.command == "DELETE":
                    store.delete_agent(revision)
                    return self.reply(200, {"deleted": True})
                if not isinstance(data.get("text"), str):
                    raise ValueError("agent 正文需要文本")
                return self.reply(200, store.revise_agent(revision, data["text"]))
            create = path == "/api/memory" and self.command == "POST"
            if create or (match and self.command in {"PUT", "DELETE"}):
                data = self.body()
                revision = data.get("revision")
                if not create and (type(revision) is not int or revision < 1):
                    raise ValueError("缺少有效的条目修订号")
                if self.command == "DELETE":
                    store.forget(match[1], revision)
                    return self.reply(200, {"deleted": True})
                if not all(isinstance(data.get(k), str) for k in ("title", "text", "kind")):
                    raise ValueError("条目需要类型、标题和正文")
                if create:
                    item = store.save_entry({}, data["title"], data["text"], data["kind"], "user")
                else:
                    item = store.save_entry({}, data["title"], data["text"], data["kind"], "user",
                                            revision=revision, item_id=match[1])
                return self.reply(201 if create else 200, item)
            return self.reply(404, {"error": "没有该资源"})

        def handle_request(self):
            try:
                self.dispatch()
            except PermissionError as exc:
                self.reply(403, {"error": str(exc)})
            except RevisionConflict as exc:
                self.reply(409, {"error": str(exc)})
            except (ValueError, KeyError) as exc:
                self.reply(400, {"error": str(exc)})
            except (ConnectionResetError, BrokenPipeError):
                pass
            except OSError:
                self.reply(500, {"error": "无法访问项目文件，请检查文件权限"})

        do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = handle_request

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.token = token
    return server


def serve(store: Store, port: int, open_browser: str = "auto") -> None:
    with create_server(store, port) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(url, flush=True)
        desktop = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        should_open = open_browser == "always" or (
            open_browser == "auto" and sys.stdin.isatty() and sys.stdout.isatty()
            and (sys.platform == "darwin" or desktop))
        if should_open:
            try:
                opened = webbrowser.open(url)
                if not opened:
                    print("无法自动打开浏览器；请手动访问上面的地址。", file=sys.stderr, flush=True)
            except (OSError, RuntimeError):
                print("无法自动打开浏览器；请手动访问上面的地址。", file=sys.stderr, flush=True)
        server.serve_forever()
