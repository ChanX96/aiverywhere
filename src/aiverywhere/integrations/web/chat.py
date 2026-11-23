"""In-memory chat sessions for the loopback console."""

from __future__ import annotations

import asyncio
import re
import threading
import time

from ...core.agent import Task, executor
from ...core.store import Store

SESSION = re.compile(r"[A-Za-z0-9_-]{8,64}\Z")
MAX_MESSAGE = 32_000


class ChatSessions:
    def __init__(self, store: Store):
        self.store = store
        self.lock = threading.Lock()
        self.records: dict[str, dict] = {}

    def _check(self, session, message, writable, exec_allowed, network_allowed):
        if not isinstance(session, str) or not SESSION.fullmatch(session):
            raise ValueError("会话标识无效")
        if not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE:
            raise ValueError("消息需要 1–32,000 个字符")
        if (type(writable) is not bool or type(exec_allowed) is not bool
                or type(network_allowed) is not bool):
            raise ValueError("writable、exec 和 network 需要布尔值")

    def start(self, session: str, message: str, writable: bool,
              exec_allowed: bool = False, network_allowed: bool = True) -> dict:
        self._check(session, message, writable, exec_allowed, network_allowed)
        limits = self.store.defaults()
        with self.lock:
            record = self.records.get(session)
            new = record is None
            if record and record["thread"] and record["thread"].is_alive():
                raise ValueError("上一条消息仍在处理")
            if (record is None or record["writable"] != writable
                    or record["exec"] != exec_allowed
                    or record["network"] != network_allowed):
                record = {"task": Task(self.store, writable=writable, exec_allowed=exec_allowed,
                                       network_allowed=network_allowed, entry="web"),
                          "writable": writable, "exec": exec_allowed,
                          "network": network_allowed,
                          "thread": None, "started": 0.0, "finished": None,
                          "stream_text": "", "thinking": ""}
                self.records[session] = record
                new = True
            thread = threading.Thread(target=self._run, args=(record, message, limits), daemon=True)
            record["thread"] = thread
            record["started"] = time.time()
            record["finished"] = None
            record["stream_text"] = ""
            record["thinking"] = ""
            thread.start()
            return {"session": session, "task_id": record["task"].id, "status": "running",
                    "started": record["started"], "writable": writable,
                    "exec": exec_allowed, "network": network_allowed, "new_session": new}

    def _run(self, record: dict, message: str, limits: dict) -> None:
        task = record["task"]
        def append(field: str, delta: str) -> None:
            if not delta:
                return
            with self.lock:
                record[field] = (record.get(field, "") + delta)[-200_000:]

        try:
            async def run():
                import httpx
                async with httpx.AsyncClient(timeout=60) as client:
                    await task.run(message, executor(client, None, self.store),
                                   max_turns=limits["max_turns"], timeout=limits["timeout"],
                                   on_text=lambda delta: append("stream_text", delta),
                                   on_thinking=lambda delta: append("thinking", delta))
            asyncio.run(run())
        except BaseException as exc:
            if task.status in {"queued", "running"}:
                task.status, task.error = "failed", str(exc) or type(exc).__name__
        finally:
            with self.lock:
                record["finished"] = time.time()

    def state(self, session: str) -> dict:
        if not isinstance(session, str) or not SESSION.fullmatch(session):
            raise ValueError("会话标识无效")
        with self.lock:
            record = self.records.get(session)
            if record is None:
                return {"session": session, "status": "idle", "new_session": True}
            task = record["task"]
            result = task.result()
            if record["thread"] and record["thread"].is_alive() and result["status"] in {"queued", "running"}:
                result["status"] = "running"
            result.update(session=session, started=record["started"], finished=record["finished"],
                          writable=record["writable"], exec_allowed=record["exec"],
                          network_allowed=record["network"],
                          stream_text=record.get("stream_text", ""),
                          thinking=record.get("thinking", ""),
                          streaming=bool(record["thread"] and record["thread"].is_alive()
                                         and result["status"] == "running"),
                          elapsed=max(0.0, (record["finished"] or time.time()) - record["started"]))
            return result

    def reset(self, session: str) -> dict:
        if not isinstance(session, str) or not SESSION.fullmatch(session):
            raise ValueError("会话标识无效")
        with self.lock:
            record = self.records.get(session)
            if record and record["thread"] and record["thread"].is_alive():
                # The worker sets the task status before its thread fully exits.
                # A completed/failed task is safe to reset; only a genuinely
                # queued/running task must be rejected.
                if record["task"].result().get("status") in {"queued", "running"}:
                    raise ValueError("任务运行中，不能重置会话")
            self.records.pop(session, None)
        return {"session": session, "reset": True}
