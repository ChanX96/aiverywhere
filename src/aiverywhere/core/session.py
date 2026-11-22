"""Durable, append-only CLI sessions.

A session is intentionally small: one JSONL file per conversation plus a lock
file.  Raw turns are never rewritten.  A summary is an additional event and
only changes the context sent to the model; the journal remains auditable.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from .store import Store


SESSION_SCHEMA = 1
SESSION_ID = re.compile(r"^[0-9a-f]{32}$")
EVENT_LIMIT = 16 * 1024 * 1024
FILE_LIMIT = 256 * 1024 * 1024
EVENT_TYPES = {"turn_start", "turn", "turn_error", "summary", "permission", "rename"}


class SessionError(ValueError):
    """A session file or operation is not safe to use."""


class SessionBusy(SessionError):
    """Another process currently owns this session."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _safe_root(store: Store) -> Path:
    data = store.data
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    base = data / "sessions"
    if base.is_symlink():
        raise PermissionError("会话目录不能是符号链接")
    base.mkdir(mode=0o700, exist_ok=True)
    if not base.resolve().is_relative_to(store.home.resolve()):
        raise PermissionError("会话目录必须位于实例内")
    root = base / store.memory.key
    if root.is_symlink():
        raise PermissionError("项目会话目录不能是符号链接")
    root.mkdir(mode=0o700, exist_ok=True)
    return root


class SessionStore:
    def __init__(self, store: Store):
        self.store = store
        self.root = _safe_root(store)

    def _path(self, ident: str) -> Path:
        if not isinstance(ident, str) or not SESSION_ID.fullmatch(ident):
            raise SessionError("session id 必须是 32 位小写十六进制")
        path = self.root / f"{ident}.jsonl"
        if path.is_symlink():
            raise PermissionError("会话文件不能是符号链接")
        return path

    def create(self) -> "Session":
        ident = os.urandom(16).hex()
        path = self._path(ident)
        header = {
            "schema": SESSION_SCHEMA,
            "type": "session",
            "session_id": ident,
            "project_key": self.store.memory.key,
            "created": _now(),
            "task_id": ident,
        }
        stream = path.open("xb")
        try:
            os.fchmod(stream.fileno(), 0o600)
            stream.write((_json(header) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        finally:
            stream.close()
        session = Session(self, ident, path, header)
        session.acquire()
        return session

    def open(self, ident: str) -> "Session":
        path = self._path(ident)
        if not path.is_file():
            raise SessionError(f"session 不存在：{ident}")
        return Session(self, ident, path, None)

    def latest(self) -> "Session | None":
        files = sorted(self.root.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files:
            try:
                session = self.open(path.stem)
                session.load()
            except (OSError, ValueError, SessionError):
                continue
            return session
        return None

    def list(self) -> list[dict]:
        rows = []
        for path in sorted(self.root.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                session = self.open(path.stem)
                info = session.info()
            except (OSError, ValueError, SessionError):
                continue
            rows.append(info)
        return rows


class Session:
    def __init__(self, owner: SessionStore, ident: str, path: Path, header: dict | None):
        self.owner = owner
        self.store = owner.store
        self.id = ident
        self.path = path
        self.lock_path = path.with_suffix(".lock")
        self.header = header or {}
        self.events: list[dict] = []
        self._seq = 0
        self.recovered = False
        self.pending: dict | None = None
        self._lock = None
        self._loaded = False
        self._valid_offset = 0

    @contextmanager
    def locked(self) -> Iterator["Session"]:
        self.acquire()
        try:
            yield self
        finally:
            self.release()

    def acquire(self) -> None:
        if self._lock is not None:
            return
        stream = self.lock_path.open("a+b")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            stream.close()
            raise SessionBusy(f"session 正被另一个进程使用：{self.id}") from exc
        os.fchmod(stream.fileno(), 0o600)
        self._lock = stream

    def release(self) -> None:
        if self._lock is None:
            return
        try:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_UN)
        finally:
            self._lock.close()
            self._lock = None

    def _require_lock(self) -> None:
        if self._lock is None:
            raise SessionError("写入 session 前必须持有锁")

    def load(self) -> "Session":
        if self._loaded:
            return self
        raw = self.path.read_bytes()
        if len(raw) > FILE_LIMIT:
            raise SessionError("session 文件超过 256 MiB")
        lines = raw.splitlines(keepends=True)
        if not lines or not lines[0].endswith(b"\n"):
            raise SessionError("session 缺少完整头记录")
        try:
            header = json.loads(lines[0][:-1])
        except ValueError as exc:
            raise SessionError("session 头不是有效 JSON") from exc
        if (not isinstance(header, dict) or header.get("schema") != SESSION_SCHEMA
                or header.get("type") != "session" or header.get("session_id") != self.id):
            raise SessionError("session 头格式不兼容")
        self.header = header
        self.events = []
        self._seq = 0
        self._valid_offset = len(lines[0])
        open_turn = None
        expected = 1
        for raw_line in lines[1:]:
            # A crash can leave a partial final line. Never parse it and never
            # append after it; the next writer truncates back to this offset.
            if not raw_line.endswith(b"\n"):
                self.recovered = True
                break
            try:
                event = json.loads(raw_line[:-1])
            except ValueError:
                self.recovered = True
                break
            if (not isinstance(event, dict) or event.get("seq") != expected
                    or event.get("type") not in EVENT_TYPES):
                self.recovered = True
                break
            if event["type"] == "turn_start":
                open_turn = event.get("turn_id")
            elif event["type"] in {"turn", "turn_error"}:
                if open_turn is not None and event.get("turn_id") == open_turn:
                    open_turn = None
            self.events.append(event)
            self._seq = expected
            self._valid_offset += len(raw_line)
            expected += 1
        if open_turn is not None:
            self.recovered = True
            self.pending = next((e for e in reversed(self.events)
                                 if e.get("type") == "turn_start" and e.get("turn_id") == open_turn), None)
        self._loaded = True
        return self

    def _append(self, event_type: str, **payload) -> int:
        self._require_lock()
        self.load()
        event = {"seq": self._seq + 1, "type": event_type, "created": _now(), **payload}
        encoded = (_json(event) + "\n").encode()
        if len(encoded) > EVENT_LIMIT:
            raise SessionError("单条 session 事件超过 16 MiB")
        with self.path.open("r+b") as stream:
            if self._valid_offset < self.path.stat().st_size:
                stream.truncate(self._valid_offset)
                stream.flush()
                os.fsync(stream.fileno())
            stream.seek(0, os.SEEK_END)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        self.events.append(event)
        self._seq += 1
        self._valid_offset += len(encoded)
        return self._seq

    def rename(self, name: str) -> int:
        if not isinstance(name, str):
            raise ValueError("session 名称需要 1–80 个可打印字符")
        name = name.strip()
        if not 1 <= len(name) <= 80 or any(ord(char) < 32 for char in name):
            raise ValueError("session 名称需要 1–80 个可打印字符")
        return self._append("rename", name=name, task_id=self.id)

    def display_name(self) -> str | None:
        self.load()
        for event in reversed(self.events):
            if event.get("type") == "rename":
                value = event.get("name")
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    def begin_turn(self, prompt: str) -> str:
        turn_id = uuid4().hex
        self._append("turn_start", turn_id=turn_id, prompt=prompt, task_id=self.id)
        return turn_id

    def finish_turn(self, turn_id: str, messages: list, answer: str, status: str = "completed") -> int:
        seq = self._append("turn", turn_id=turn_id, messages=messages,
                           answer=answer, status=status, task_id=self.id)
        self.pending = None
        return seq

    def fail_turn(self, turn_id: str, status: str, error: str) -> int:
        seq = self._append("turn_error", turn_id=turn_id, status=status, error=error[:2000],
                           task_id=self.id)
        self.pending = None
        return seq

    def append_summary(self, text: str, *, method: str, covers_messages: int,
                       covers_turn: int | None = None) -> int:
        return self._append("summary", text=text[:16000], method=method,
                            covers_messages=max(0, covers_messages),
                            covers_turn=covers_turn)

    def append_permission(self, capability: str, allowed: bool, source: str) -> int:
        return self._append("permission", capability=capability, allowed=bool(allowed),
                            source=source, task_id=self.id)

    def turns(self) -> list[dict]:
        self.load()
        return [event for event in self.events if event.get("type") == "turn"]

    def history(self) -> list:
        self.load()
        result = []
        for event in self.turns():
            messages = event.get("messages")
            if isinstance(messages, list):
                result.extend(message for message in messages if isinstance(message, dict))
        return result

    def summary(self) -> dict | None:
        self.load()
        for event in reversed(self.events):
            if event.get("type") == "summary":
                return event
        return None

    def info(self) -> dict:
        self.load()
        summary = self.summary()
        return {
            "id": self.id,
            "name": self.display_name(),
            "created": self.header.get("created"),
            "updated": self.events[-1].get("created") if self.events else self.header.get("created"),
            "turns": len(self.turns()),
            "pending": bool(self.pending),
            "recovered": self.recovered,
            "summary": bool(summary),
            "summary_method": summary.get("method") if summary else None,
            "bytes": self.path.stat().st_size,
        }

    def resolve_pending(self) -> bool:
        """Close a turn interrupted by a crash without pretending it succeeded."""
        self.load()
        if self.pending is None:
            return False
        self._append("turn_error", turn_id=self.pending.get("turn_id"),
                     status="result_unknown", error="进程在回合完成前中断；结果未知。",
                     task_id=self.id)
        self.pending = None
        self.recovered = True
        return True
