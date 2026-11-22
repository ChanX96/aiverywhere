"""One durable task per inbound message. The gateway owns the WeChat connection."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from ..core.agent import Task, executor
from ..core.store import Store, worker_alive


def settings(store: Store) -> dict:
    cfg = store.configuration().get("wechat", {})
    if not isinstance(cfg, dict) or not all(isinstance(cfg.get(k), str) and cfg[k].strip()
            for k in ("project", "account", "conversation", "url")):
        raise ValueError("config.json 的 wechat 分区需要 project、account、conversation、url")
    url = urlsplit(cfg["url"])
    if (cfg["project"] != str(store.project) or url.scheme not in {"https", "http"} or not url.hostname
            or url.username or url.query or url.fragment):
        raise ValueError("微信网关地址或项目绑定无效")
    for key in ("idempotent_send", "receipt_lookup"):
        if type(cfg.get(key, False)) is not bool:
            raise ValueError(f"{key} 需要布尔值")
    for key in ("timeout", "max_turns"):
        if key in cfg and (type(cfg[key]) is not int or cfg[key] <= 0):
            raise ValueError(f"{key} 需要正整数")
    if type(cfg.get("progress_after", 120)) is not int or cfg.get("progress_after", 120) < 0:
        raise ValueError("progress_after 需要非负秒数，0 表示只提醒有证据的偏离")
    if "auth_token" in cfg and not isinstance(cfg["auth_token"], str):
        raise ValueError("auth_token 需要字符串")
    limits = store.defaults()
    cfg.setdefault("timeout", limits["timeout"])
    cfg.setdefault("max_turns", limits["max_turns"])
    cfg["url"] = cfg["url"].rstrip("/")
    return cfg


def receipt(record: dict) -> dict:
    route = record["wechat"]
    return {"task_id": record["result"]["task_id"], "status": record["result"]["status"],
            "delivery": route["state"], "receipt": route.get("receipt"), "detail": route.get("detail")}


def status(store: Store, ident: str) -> dict:
    record = store.snapshot(runtime_only=True).get("jobs", {}).get(ident, {})
    if "wechat" not in record or record["project"] != str(store.project):
        raise ValueError("本项目没有这条微信任务")
    return receipt(record) | {k: record["result"][k] for k in ("answer", "error") if record["result"].get(k)} | {
        "checkpoint": record["wechat"].get("checkpoint"), "progress": record["wechat"].get("progress")}


def receive(store: Store, message: dict) -> dict:
    cfg = settings(store)
    if not isinstance(message, dict) or any(message.get(k) != cfg[k] for k in ("account", "conversation")):
        raise PermissionError("微信消息不属于本项目绑定的账号和会话")
    for key, limit in (("message_id", 256), ("text", 65536)):
        if not isinstance(message.get(key), str) or not message[key].strip() or len(message[key]) > limit:
            raise ValueError(f"无效的微信消息字段 {key}")
    address = {k: message[k] for k in ("account", "conversation", "message_id")}
    digest = hashlib.sha256(json.dumps([str(store.project), address], sort_keys=True).encode()).hexdigest()
    ident = "wechat:" + digest
    with store.edit() as state:
        jobs = state.setdefault("jobs", {})
        if ident in jobs:
            if jobs[ident]["wechat"]["text"] != message["text"]:
                raise ValueError("同一微信消息 ID 携带了不同正文")
        else:
            jobs[ident] = {"project": str(store.project), "result": {"task_id": ident, "status": "queued"},
                           "wechat": address | {"url": cfg["url"], "state": "queued", "text": message["text"]}}
        return receipt(jobs[ident])


def next_job(store: Store, state=None) -> str | None:
    now = time.time()
    if state is None:
        state = store.snapshot(runtime_only=True)
    for key, record in state.get("jobs", {}).items():
        route = record.get("wechat")
        if not route or record["project"] != str(store.project):
            continue
        phase = route["state"]
        if phase in {"delivered", "unknown", "rejected"} or phase == "accepted" and not route.get("poll"):
            continue
        if phase in {"working", "sending"} and worker_alive(record, now):
            return None
        if phase == "ready" and route.get("progress", {}).get("state") == "sending" and worker_alive(record, now):
            return None
        if route.get("next", 0) <= now:
            return key
        if phase != "accepted":
            return None
    return None


async def send_or_check(client, cfg, route, ident, text, *, uncertain: bool) -> dict:
    address = {"id": ident, "account": route["account"], "conversation": route["conversation"],
               "reply_to": route["message_id"]}
    endpoint = route["url"] + "/messages"
    headers = {"Authorization": "Bearer " + cfg["auth_token"]} if cfg.get("auth_token") else {}
    lookup, idempotent = cfg.get("receipt_lookup", False), cfg.get("idempotent_send", False)
    response = None
    try:
        if uncertain and lookup:
            response = await client.get(endpoint + "/" + ident, headers=headers, timeout=15)
            if response.status_code == 404:
                response = None
        if response is None:
            if uncertain and (not idempotent or route.get("receipt")):
                return {"state": "unknown", "detail": "网关无法核实上次发送结果"}
            response = await client.post(endpoint, headers=headers | {"Idempotency-Key": ident},
                                         json=address | {"text": text}, timeout=15)
        if response.status_code >= 500 or response.status_code in {408, 429}:
            raise httpx.RequestError(f"HTTP {response.status_code}")
        if not response.is_success:
            return {"state": "unknown" if uncertain else "rejected", "detail": f"HTTP {response.status_code}"}
        ack = response.json()
        if (not isinstance(ack, dict) or any(ack.get(k) != value for k, value in address.items())
                or ack.get("state") not in {"accepted", "delivered"} or not isinstance(ack.get("receipt"), str)
                or not ack["receipt"]):
            return {"state": "unknown", "detail": "回执缺少原会话、消息标识或送达状态"}
        return {"state": ack["state"], "receipt": ack["receipt"], "poll": lookup, "detail": None}
    except (httpx.HTTPError, ValueError) as exc:
        return {"state": "verify" if lookup or idempotent else "unknown", "detail": type(exc).__name__}


async def process(store: Store, client, key: str) -> dict:
    token = uuid4().hex
    with store.edit() as state:
        if next_job(store, state) != key:
            return {"status": "busy"}
        record = state["jobs"][key]
        route = record["wechat"]
        try:
            cfg = settings(store)
        except (OSError, ValueError) as exc:
            route.update(next=time.time() + 60, detail=str(exc))
            return receipt(record)
        if any(cfg[k] != route[k] for k in ("url", "account", "conversation")):
            route.update(state="unknown", detail="绑定已变更，请核对原会话")
            state.setdefault("notices", {}).setdefault(str(store.project), {})[key] = receipt(record)
            return receipt(record)
        phase = route["state"]
        if route.get("progress", {}).get("state") == "sending":
            route["progress"]["state"] = "unknown"
        if phase == "working":
            record["result"].update(status="interrupted", error="处理被中断，已经发起的动作需核对")
        generate = phase == "queued"
        if generate:
            record["result"]["status"] = "running"
        route.update(state="working" if generate else "sending", lease=token)
        record.update(pid=os.getpid(), expires=time.time() + (cfg["timeout"] + 30 if generate else 60))
        previous = record["result"]
    if generate:
        task = Task(store, id=key, entry="wechat")
        changed = asyncio.Event()
        point = {}

        def checkpoint(values):
            if point == values:
                return
            point.clear()
            point.update(values)
            if values.get("concern"):
                task.review_requested = True
            changed.set()
            with store.edit() as state:
                target = state["jobs"][key]["wechat"]
                if target.get("lease") == token:
                    target["checkpoint"] = " ".join(values["summary"].split())[:240]

        async def monitor():
            # Runs inside the wake worker. A new checkpoint restarts the idle window.
            delay = cfg.get("progress_after", 120)
            while task.status == "running" and not point.get("concern"):
                try:
                    await asyncio.wait_for(changed.wait(), timeout=delay or None)
                    changed.clear()
                except asyncio.TimeoutError:
                    break
            if task.status != "running":
                return
            concern = " ".join(point.get("concern", "").split())
            note = "进度待核对：" + concern if concern else f"已有 {delay} 秒没有新进展记录，任务仍在处理。"
            if not concern:
                task.review_requested = True
            with store.edit() as state:
                target = state["jobs"][key]["wechat"]
                if target.get("lease") != token or "progress" in target:
                    return
                target["progress"] = {"text": note, "state": "sending"}
            try:
                binding = settings(store)
                if any(binding[k] != route[k] for k in ("url", "account", "conversation")):
                    raise ValueError("会话绑定已变更")
                outcome = await send_or_check(client, binding, route, key + ".progress", note, uncertain=False)
            except (OSError, ValueError):
                outcome = {"state": "unknown"}
            with store.edit() as state:
                progress = state["jobs"][key]["wechat"]["progress"]
                progress.update(state="unknown" if outcome["state"] == "verify" else outcome["state"],
                                receipt=outcome.get("receipt"))

        watcher = asyncio.create_task(monitor())
        try:
            await task.run(route["text"], executor(client, None, store), timeout=cfg["timeout"],
                           max_turns=cfg["max_turns"], checkpoint=checkpoint)
        except asyncio.CancelledError:
            task.status, task.error = "interrupted", "处理被中断，已经发起的动作需核对"
            raise
        except (OSError, ValueError) as exc:
            task.status, task.error = "failed", str(exc)
        finally:
            try:
                with store.edit() as state:
                    current = state["jobs"][key]
                    if current["wechat"].get("lease") == token:
                        current["result"] = task.result()
                        current["wechat"].update(state="ready", next=0)
                        current["wechat"].pop("lease")
            finally:
                # Wake the idle monitor explicitly. A progress send already in flight
                # finishes recording its receipt before the worker exits.
                changed.set()
                await asyncio.gather(watcher, return_exceptions=True)
        return receipt(current)
    text = previous.get("answer") or ("任务未完成。" + (previous.get("error") or previous["status"]))
    outcome = await send_or_check(client, cfg, route, key, text, uncertain=phase in {"verify", "accepted", "sending"})
    with store.edit() as state:
        current = state["jobs"][key]
        target = current["wechat"]
        if target.get("lease") == token:
            attempts = target.get("attempts", 0) + 1
            target.update(outcome, attempts=attempts, next=time.time() + min(300, 2 ** min(9, attempts)))
            target.pop("lease")
            if outcome["state"] in {"unknown", "rejected"}:
                state.setdefault("notices", {}).setdefault(str(store.project), {})[key] = {
                    "task_id": key, "delivery": outcome["state"], "detail": outcome["detail"]}
        return receipt(current)
