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

    def _check(self, session, message, writable):
        if not isinstance(session, str) or not SESSION.fullmatch(session):
            raise ValueError("会话标识无效")
        if not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE:
            raise ValueError("消息需要 1–32,000 个字符")
        if type(writable) is not bool:
            raise ValueError("writable 需要布尔值")

    def start(self, session: str, message: str, writable: bool) -> dict:
        self._check(session, message, writable)
        limits = self.store.defaults()
        with self.lock:
            record = self.records.get(session)
            new = record is None
            if record and record["thread"] and record["thread"].is_alive():
                raise ValueError("上一条消息仍在处理")
            if record is None or record["writable"] != writable:
                record = {"task": Task(self.store, writable=writable, entry="web"),
                          "writable": writable, "thread": None, "started": 0.0, "finished": None}
                self.records[session] = record
                new = True
            thread = threading.Thread(target=self._run, args=(record, message, limits), daemon=True)
            record["thread"] = thread
            record["started"] = time.time()
            record["finished"] = None
            thread.start()
            return {"session": session, "task_id": record["task"].id, "status": "running",
                    "started": record["started"], "writable": writable, "new_session": new}

    def _run(self, record: dict, message: str, limits: dict) -> None:
        task = record["task"]
        try:
            async def run():
                import httpx
                async with httpx.AsyncClient(timeout=60) as client:
                    await task.run(message, executor(client, None, self.store),
                                   max_turns=limits["max_turns"], timeout=limits["timeout"])
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
                          writable=record["writable"],
                          elapsed=max(0.0, (record["finished"] or time.time()) - record["started"]))
            return result

    def reset(self, session: str) -> dict:
        if not isinstance(session, str) or not SESSION.fullmatch(session):
            raise ValueError("会话标识无效")
        with self.lock:
            record = self.records.pop(session, None)
            if record and record["thread"] and record["thread"].is_alive():
                self.records[session] = record
                raise ValueError("任务运行中，不能重置会话")
        return {"session": session, "reset": True}
