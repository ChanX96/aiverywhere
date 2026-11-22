"""Calendar wakeups and delivery scheduling; the core agent loop lives elsewhere."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from .agent import Task, executor
from .store import Store, worker_alive


def add_plan(store: Store, args) -> dict:
    first = datetime.fromisoformat(args.at)
    if args.timezone:
        zone = ZoneInfo(args.timezone)
        first = first.astimezone(zone) if first.tzinfo else first.replace(tzinfo=zone)
    if first.tzinfo is None:
        raise ValueError("--at 需要带 UTC 偏移，或通过 --timezone 指定时区")
    if not args.prompt.strip():
        raise ValueError("定时任务目标不能为空")
    plan = {"id": uuid4().hex, "project": str(store.project), "prompt": args.prompt,
            "first": first.isoformat(), "zone": args.timezone, "repeat": args.repeat,
            "index": 0, "enabled": True, "grace": args.grace, "model": args.model,
            "writable": args.allow_write, "mcp": args.mcp}
    with store.edit() as state:
        state.setdefault("plans", {})[plan["id"]] = plan
    return plan_info(plan)


def slot(plan: dict, index: int) -> datetime:
    first = datetime.fromisoformat(plan["first"])
    if plan["zone"]:
        first = first.astimezone(ZoneInfo(plan["zone"]))
    if index == 0:
        return first
    days = {"once": 0, "daily": 1, "weekly": 7}[plan["repeat"]]
    return first + timedelta(days=days * index)


def plan_info(plan: dict) -> dict:
    return {k: plan[k] for k in ("id", "prompt", "repeat", "enabled", "grace")} | {
        "next_at": slot(plan, plan["index"]).isoformat() if plan["enabled"] else None}


def plans(store: Store, current=None) -> list[dict]:
    if current is None:
        current = store.snapshot(runtime_only=True)
    return [p for p in current.get("plans", {}).values()
            if p["project"] == str(store.project)]


def due_index(plan: dict, horizon: float) -> int | None:
    """Find the latest elapsed calendar slot without iterating all missed periods."""
    if not plan["enabled"] or slot(plan, plan["index"]).timestamp() > horizon:
        return None
    if plan["repeat"] == "once":
        return 0
    first = slot(plan, 0)
    days = (datetime.fromtimestamp(horizon, first.tzinfo).date() - first.date()).days
    index = days // (7 if plan["repeat"] == "weekly" else 1)
    if slot(plan, index).timestamp() > horizon:
        index -= 1
    return index


def claim_due(store: Store, now: float, capacity: int, *, display=None, current=None) -> list[tuple]:
    """capacity=0 only reconciles overdue slots for the next conversation."""
    def horizon(plan):
        return now if capacity else now - plan["grace"]

    scope = str(store.project)
    def interrupted(state):
        for collection in ("runs", "jobs"):
            for record in state.get(collection, {}).values():
                result = record.get("result", record)
                if (record.get("project") == scope and result["status"] == "running"
                        and not worker_alive(record, now)):
                    yield result

    if current is None:
        current = store.snapshot(runtime_only=True)
    due = any(p["project"] == scope and due_index(p, horizon(p)) is not None
              for p in current.get("plans", {}).values())
    pending_notice = display is not None and current.get("notices", {}).get(scope)
    if not (due or pending_notice or next(interrupted(current), None)):
        return []
    claimed = []
    with store.edit() as state:
        for result in interrupted(state):
            result.update(status="interrupted", error="执行者已中断，已发起动作的结果待核对")
            state.setdefault("notices", {}).setdefault(scope, {})[result["task_id"]] = {
                k: result[k] for k in ("task_id", "status", "error")}
        for plan in state.get("plans", {}).values():
            if plan["project"] != scope:
                continue
            last = due_index(plan, horizon(plan))
            if last is None:
                continue
            when = slot(plan, last)
            runnable = capacity > 0 and now - when.timestamp() < plan["grace"]
            if runnable and len(claimed) == capacity:
                continue
            missed = last - plan["index"] + 1 - int(runnable)
            if missed:
                notices = state.setdefault("notices", {}).setdefault(scope, {})
                previous = notices.get(plan["id"], {})
                notices[plan["id"]] = {"plan_id": plan["id"], "prompt": plan["prompt"],
                    "count": previous.get("count", 0) + missed, "status": "missed",
                    "last_at": slot(plan, plan["index"] + missed - 1).isoformat()}
            if runnable:
                ident = f"{plan['id']}.{last}"
                state.setdefault("runs", {})[ident] = {"task_id": ident, "project": scope,
                    "status": "running", "scheduled_at": when.isoformat(), "started": now,
                    "pid": os.getpid(), "expires": now + 210}
                claimed.append((ident, plan.copy()))
            plan["index"] = last + 1
            plan["enabled"] = plan["repeat"] != "once"
        if display is not None:
            notices = state.get("notices", {}).pop(scope, {})
            if notices:
                display(list(notices.values()))
    return claimed


def show_notices(store: Store, display) -> None:
    claim_due(store, time.time(), 0, display=display)


def disable(store: Store, ident: str) -> None:
    with store.edit() as state:
        plan = state.get("plans", {}).get(ident)
        if not plan or plan["project"] != str(store.project):
            raise ValueError("本项目没有该计划")
        plan["enabled"] = False


async def execute_plan(store: Store, ident: str, plan: dict, client, host: str | None) -> dict:
    task = Task(store, id=ident, writable=plan["writable"], entry="scheduled", host=host,
                mcp_servers=tuple(plan["mcp"]))
    try:
        limits = store.defaults()
        await task.run(plan["prompt"], executor(client, plan["model"], store),
                       max_turns=limits["max_turns"], timeout=limits["timeout"])
    except (OSError, ValueError) as exc:
        task.status, task.error = "failed", str(exc)
    finally:
        with store.edit() as state:
            state["runs"][ident].update(task.result(), finished=time.time())
            if task.status != "completed":
                state.setdefault("notices", {}).setdefault(str(store.project), {})[ident] = {
                    "task_id": ident, "status": task.status, "error": task.error}
    return task.result()
