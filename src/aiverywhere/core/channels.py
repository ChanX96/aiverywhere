"""Channel-neutral inbound/outbound routing.

Gateways (WeChat, Feishu, iMessage or a local bridge) speak one small webhook
envelope.  The core persists the originating channel on the task and always
sends the answer back through that same channel.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from urllib.parse import urlsplit

import httpx

from .agent import Task, executor
from .store import Store, worker_alive


CHANNEL_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DEFAULT_SEND_PATH = "/messages"


def configs(store: Store) -> dict[str, dict]:
    configuration = store.configuration()
    raw = configuration.get("channels")
    if raw is None and isinstance(configuration.get("wechat"), dict):
        legacy = configuration["wechat"]
        if legacy:
            raw = {"wechat": {key: legacy[key] for key in
                              ("url", "idempotent_send", "receipt_lookup", "account", "conversation",
                               "timeout", "max_turns") if key in legacy}}
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("config.json 的 channels 需要对象")
    limits = store.defaults()
    result = {}
    for ident, value in raw.items():
        if not isinstance(ident, str) or not CHANNEL_ID.fullmatch(ident):
            raise ValueError("channel id 只支持 1–64 个字母、数字、下划线或连字符")
        if not isinstance(value, dict):
            raise ValueError(f"channel {ident} 需要对象")
        allowed = {"type", "url", "send_path", "auth_token", "auth_token_env",
                   "account", "conversation", "idempotent_send", "receipt_lookup",
                   "timeout", "max_turns"}
        if value.keys() - allowed:
            raise ValueError(f"channel {ident} 含未知字段")
        kind = value.get("type", "webhook")
        if kind != "webhook":
            raise ValueError(f"channel {ident} 的 type 目前只支持 webhook")
        url = value.get("url")
        if not isinstance(url, str):
            raise ValueError(f"channel {ident} 需要 url")
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username:
            raise ValueError(f"channel {ident} 的 url 无效")
        send_path = value.get("send_path", DEFAULT_SEND_PATH)
        if not isinstance(send_path, str) or not send_path.startswith("/"):
            raise ValueError(f"channel {ident} 的 send_path 需要以 / 开头")
        token = value.get("auth_token")
        token_env = value.get("auth_token_env")
        if token is not None and not isinstance(token, str):
            raise ValueError(f"channel {ident}.auth_token 需要字符串")
        if token_env is not None and (not isinstance(token_env, str) or not token_env.isidentifier()):
            raise ValueError(f"channel {ident}.auth_token_env 需要合法环境变量名")
        for key in ("idempotent_send", "receipt_lookup"):
            if type(value.get(key, False)) is not bool:
                raise ValueError(f"channel {ident}.{key} 需要布尔值")
        timeout = value.get("timeout", limits["timeout"])
        max_turns = value.get("max_turns", limits["max_turns"])
        if type(timeout) is not int or timeout <= 0 or type(max_turns) is not int or max_turns <= 0:
            raise ValueError(f"channel {ident} 的 timeout/max_turns 需要正整数")
        result[ident] = {
            "id": ident, "type": kind, "url": url.rstrip("/"),
            "send_path": send_path, "auth_token": token,
            "auth_token_env": token_env,
            "account": value.get("account"), "conversation": value.get("conversation"),
            "idempotent_send": value.get("idempotent_send", False),
            "receipt_lookup": value.get("receipt_lookup", False),
            "timeout": timeout, "max_turns": max_turns,
            "project": str(store.project),
        }
    return result


def _normalize(store: Store, channel_id: str, message: dict) -> tuple[dict, dict]:
    channels = configs(store)
    if channel_id not in channels:
        raise PermissionError(f"没有配置 channel {channel_id}")
    cfg = channels[channel_id]
    if not isinstance(message, dict):
        raise ValueError("消息需要 JSON 对象")
    for key, limit in (("account", 200), ("conversation", 500), ("message_id", 256), ("text", 65536)):
        if not isinstance(message.get(key), str) or not message[key].strip() or len(message[key]) > limit:
            raise ValueError(f"无效的 channel 消息字段 {key}")
    if cfg["account"] and message["account"] != cfg["account"]:
        raise PermissionError("消息账号不属于该 channel")
    if cfg["conversation"] and message["conversation"] != cfg["conversation"]:
        raise PermissionError("消息会话不属于该 channel")
    return cfg, message


def receive(store: Store, message: dict, channel_id: str | None = None) -> dict:
    if channel_id is None:
        channel_id = message.get("channel") if isinstance(message, dict) else None
    if not isinstance(channel_id, str) or not CHANNEL_ID.fullmatch(channel_id):
        raise ValueError("message.channel 需要 1–64 个字母、数字、下划线或连字符")
    cfg, message = _normalize(store, channel_id, message)
    address = {key: message[key] for key in ("account", "conversation", "message_id")}
    digest = hashlib.sha256(json.dumps(
        [str(store.project), channel_id, address], sort_keys=True).encode()).hexdigest()
    ident = f"channel:{digest}"
    with store.edit() as state:
        jobs = state.setdefault("jobs", {})
        if ident in jobs:
            if jobs[ident]["channel"]["text"] != message["text"]:
                raise ValueError("同一通道消息 ID 携带了不同正文")
        else:
            jobs[ident] = {"project": str(store.project),
                           "result": {"task_id": ident, "status": "queued"},
                           "channel": address | {"id": channel_id, "url": cfg["url"],
                                                 "state": "queued", "text": message["text"]}}
        return receipt(jobs[ident])


def receipt(record: dict) -> dict:
    route = record["channel"]
    return {"task_id": record["result"]["task_id"], "channel": route["id"],
            "status": record["result"]["status"], "delivery": route["state"],
            "receipt": route.get("receipt"), "detail": route.get("detail")}


def status(store: Store, ident: str) -> dict:
    record = store.snapshot(runtime_only=True).get("jobs", {}).get(ident, {})
    if "channel" not in record or record["project"] != str(store.project):
        raise ValueError("本项目没有这条通道任务")
    return receipt(record) | {k: record["result"][k] for k in ("answer", "error") if record["result"].get(k)}


def next_job(store: Store, state=None) -> str | None:
    now = time.time()
    if state is None:
        state = store.snapshot(runtime_only=True)
    for key, record in state.get("jobs", {}).items():
        route = record.get("channel")
        if not route or record["project"] != str(store.project):
            continue
        phase = route["state"]
        if phase in {"delivered", "unknown", "rejected"}:
            continue
        if phase == "accepted" and not route.get("poll"):
            continue
        if phase in {"working", "sending"} and worker_alive(record, now):
            return None
        if route.get("next", 0) <= now:
            return key
        if phase != "accepted":
            return None
    return None


async def _send(client, store: Store, cfg: dict, route: dict, ident: str,
                text: str, *, uncertain: bool) -> dict:
    channels = configs(store)
    if route["id"] not in channels:
        return {"state": "unknown", "detail": "原 channel 已移除"}
    current = channels[route["id"]]
    if current["url"] != route.get("url"):
        return {"state": "unknown", "detail": "channel 地址已变更，请核对原回执"}
    endpoint = current["url"] + current["send_path"]
    headers = {}
    token = current.get("auth_token") or (os.environ.get(current["auth_token_env"])
                                          if current.get("auth_token_env") else None)
    if token:
        headers["Authorization"] = "Bearer " + token
    payload = {"id": ident, "channel": route["id"], "account": route["account"],
               "conversation": route["conversation"], "reply_to": route["message_id"],
               "text": text}
    lookup, idempotent = current["receipt_lookup"], current["idempotent_send"]
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
                                         json=payload, timeout=15)
        if response.status_code >= 500 or response.status_code in {408, 429}:
            raise httpx.RequestError(f"HTTP {response.status_code}")
        if not response.is_success:
            return {"state": "unknown" if uncertain else "rejected",
                    "detail": f"HTTP {response.status_code}"}
        ack = response.json()
        if (not isinstance(ack, dict)
                or any(ack.get(k) != payload[k] for k in ("channel", "account", "conversation", "reply_to"))
                or ack.get("state") not in {"accepted", "delivered"}
                or not isinstance(ack.get("receipt"), str) or not ack["receipt"]):
            return {"state": "unknown", "detail": "回执缺少原通道、会话、消息标识或送达状态"}
        return {"state": ack["state"], "receipt": ack["receipt"],
                "poll": lookup, "detail": None}
    except (httpx.HTTPError, ValueError) as exc:
        return {"state": "verify" if lookup or idempotent else "unknown",
                "detail": type(exc).__name__}


async def process(store: Store, client, key: str) -> dict:
    token = os.urandom(16).hex()
    with store.edit() as state:
        if next_job(store, state) != key:
            return {"status": "busy"}
        record = state["jobs"].get(key)
        if not record:
            raise ValueError("通道任务不存在")
        route = record["channel"]
        try:
            cfg = configs(store).get(route["id"])
        except (OSError, ValueError) as exc:
            cfg = None
            route.update(next=time.time() + 60, detail=str(exc))
        if cfg is None:
            route.update(state="unknown", detail=route.get("detail") or "channel 配置不可用")
            return receipt(record)
        uncertain = route["state"] in {"verify", "accepted", "sending"}
        if route["state"] == "working":
            record["result"].update(status="interrupted", error="处理被中断，已经发起的动作需核对")
        generate = route["state"] == "queued"
        if generate:
            record["result"]["status"] = "running"
        route.update(state="working" if generate else "sending", lease=token)
        record.update(pid=os.getpid(), expires=time.time() + (cfg["timeout"] + 30 if generate else 60))
        previous = record["result"]
    if generate:
        task = Task(store, id=key, entry="channel")
        try:
            await task.run(route["text"], executor(client, None, store),
                           timeout=cfg["timeout"], max_turns=cfg["max_turns"])
        except asyncio.CancelledError:
            task.status, task.error = "interrupted", "处理被中断，已经发起的动作需核对"
            raise
        except (OSError, ValueError) as exc:
            task.status, task.error = "failed", str(exc)
        finally:
            with store.edit() as state:
                current = state["jobs"][key]
                if current["channel"].get("lease") == token:
                    current["result"] = task.result()
                    current["channel"].update(state="ready", next=0)
                    current["channel"].pop("lease")
        return receipt(current)
    text = previous.get("answer") or ("任务未完成。" + (previous.get("error") or previous["status"]))
    outcome = await _send(client, store, cfg, route, key, text, uncertain=uncertain)
    with store.edit() as state:
        current = state["jobs"][key]
        target = current["channel"]
        if target.get("lease") == token:
            attempts = target.get("attempts", 0) + 1
            target.update(outcome, attempts=attempts,
                          next=time.time() + min(300, 2 ** min(9, attempts)))
            target.pop("lease", None)
        return receipt(current)
