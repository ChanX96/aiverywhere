"""Submit a task to its native executor or drive client tools on a raw Messages endpoint."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import tempfile
from dataclasses import dataclass, field
from contextlib import AsyncExitStack
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable
from urllib.parse import urlsplit
from uuid import uuid4

if TYPE_CHECKING:
    import httpx

from ..platform.environment import inspect_environment
from .mcp_tools import RemoteTools
from .store import Store, file_version, skill_revision
from .tools import DISCOVER, Tools, tool, validate_arguments


@dataclass(frozen=True)
class Native:
    argv: tuple[str, ...]
    pass_env: tuple[str, ...] = ()

    async def finish(self, store: Store, instructions: str, messages: list) -> str:
        payload = json.dumps({"instructions": instructions, "messages": messages}, ensure_ascii=False).encode()
        names = ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "XDG_RUNTIME_DIR", *self.pass_env)
        env = {name: os.environ[name] for name in names if name in os.environ}
        env["AIVERYWHERE_HOME"] = str(store.home)
        store.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryFile(dir=store.data) as output:
            child = await asyncio.create_subprocess_exec(*self.argv, cwd=store.project,
                env=env, stdin=asyncio.subprocess.PIPE,
                stdout=output, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
            try:
                await child.communicate(payload)
            finally:
                if child.returncode is None:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await child.wait()
            if child.returncode:
                raise ValueError(f"原生执行器退出码 {child.returncode}，请核对宿主运行记录")
            output.seek(0)
            raw = output.read(1_048_577)
            if len(raw) > 1_048_576 or not raw.strip():
                raise ValueError("原生执行器须在标准输出返回 1 MiB 以内的非空最终答复")
            return raw.decode("utf-8").strip()


MODEL_FIELDS = {"model", "base_url", "api_key", "auth_token", "api_key_env", "auth_token_env", "max_tokens"}
APPROVAL_TOOLS = frozenset({"write_file", "edit_file", "run_command", "accept_artifact"})
CREDENTIAL_FIELDS = ("api_key", "auth_token", "api_key_env", "auth_token_env")


def executor(client, model: str | None, store: Store):
    settings = store.configuration().get("model")
    if not settings:
        return Messages(client, model)
    if "command" in settings:
        argv = settings["command"]
        names = settings.get("pass_env", [])
        if (model or settings.keys() - {"command", "project", "pass_env"} or settings.get("project") != str(store.project)
                or not isinstance(argv, list) or not argv or not all(isinstance(s, str) and s for s in argv)
                or not Path(argv[0]).is_absolute() or not isinstance(names, list)
                or not all(isinstance(name, str) and name.isidentifier() for name in names)):
            raise ValueError("原生执行器需绑定当前 project 和绝对路径 command 参数数组，模型由该命令选择")
        return Native(tuple(argv), tuple(names))
    if settings.keys() - MODEL_FIELDS:
        raise ValueError("model 分区支持 model、base_url、api_key、auth_token、api_key_env、auth_token_env、max_tokens")
    for key, value in settings.items():
        if key == "max_tokens":
            if type(value) is not int or value <= 0:
                raise ValueError("model.max_tokens 需要正整数")
        elif not isinstance(value, str):
            raise ValueError("model 分区的连接参数需要字符串")
    if sum(bool(settings.get(key)) for key in CREDENTIAL_FIELDS) > 1:
        raise ValueError("model 分区只能选择一种凭据方式")
    for key in ("api_key_env", "auth_token_env"):
        if settings.get(key) and not settings[key].isidentifier():
            raise ValueError(f"model.{key} 需要合法的环境变量名")
    return Messages(client, model, settings=settings)


class Messages:
    def __init__(self, client: httpx.AsyncClient, model: str | None, *, settings=None):
        self.client = client
        if settings is None:
            settings = {"model": os.getenv("AIVERYWHERE_MODEL") or os.getenv("ANTHROPIC_MODEL"),
                        "base_url": os.getenv("ANTHROPIC_BASE_URL"), "api_key": os.getenv("ANTHROPIC_API_KEY"),
                        "auth_token": os.getenv("ANTHROPIC_AUTH_TOKEN")}
        self.model = model or settings.get("model")
        self.max_tokens = settings.get("max_tokens", 4096)
        if type(self.max_tokens) is not int or self.max_tokens <= 0:
            raise ValueError("max_tokens 需要正整数")
        self.base = (settings.get("base_url") or "https://api.anthropic.com").rstrip("/")
        url = urlsplit(self.base)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.query or url.fragment:
            raise ValueError("模型服务地址应为 HTTP(S) 地址")
        self.headers = {"anthropic-version": "2023-06-01"}
        token = settings.get("auth_token") or self._env(settings.get("auth_token_env"))
        key = settings.get("api_key") or self._env(settings.get("api_key_env"))
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        elif key:
            self.headers["x-api-key"] = key

    @staticmethod
    def _env(name: str | None) -> str | None:
        return os.environ.get(name) if name else None

    @staticmethod
    def _http_error(exc) -> str:
        detail = (exc.response.text or "").strip().replace("\n", " ")[:500]
        suffix = f"：{detail}" if detail else ""
        hint = "；请核对 model、base_url 与工具 schema 是否被该端点接受" if exc.response.status_code == 422 else ""
        return f"模型服务返回 HTTP {exc.response.status_code}（{exc.response.reason_phrase}）{hint}{suffix}"

    async def send(self, system: str, messages: list, tools: list) -> dict:
        import httpx

        if not self.model:
            raise ValueError("请用 --model 或 AIVERYWHERE_MODEL 指定模型")
        url = self.base
        if not url.endswith("/v1/messages"):
            url += "/messages" if url.endswith("/v1") else "/v1/messages"
        if urlsplit(url).hostname == "api.anthropic.com" and len(self.headers) == 1:
            raise ValueError("请配置 api_key、auth_token 或对应的环境变量")
        try:
            response = await self.client.post(url, headers=self.headers, json={
                "model": self.model, "max_tokens": self.max_tokens, "system": system,
                "messages": messages, "tools": tools,
            })
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ValueError(self._http_error(exc)) from exc
        except httpx.RequestError as exc:
            raise ValueError(f"模型请求未完成（{type(exc).__name__}）") from exc
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("content"), list):
            raise ValueError("模型服务返回的内容不符合 Messages 协议")
        # DeepSeek/Anthropic-compatible endpoints may return thinking blocks
        # with provider-specific signatures. They are not part of our tool-loop
        # protocol; retaining a stripped block makes the next request invalid.
        data["content"] = [block for block in data["content"]
                           if isinstance(block, dict) and block.get("type") in {"text", "tool_use"}]
        return data

    async def stream_send(self, system: str, messages: list, tools: list, on_text=None) -> dict:
        import httpx

        if not self.model:
            raise ValueError("请用 --model 或 AIVERYWHERE_MODEL 指定模型")
        url = self.base
        if not url.endswith("/v1/messages"):
            url += "/messages" if url.endswith("/v1") else "/v1/messages"
        if urlsplit(url).hostname == "api.anthropic.com" and len(self.headers) == 1:
            raise ValueError("请配置 api_key、auth_token 或对应的环境变量")
        blocks: dict[int, dict] = {}
        stop_reason = None
        try:
            async with self.client.stream("POST", url, headers=self.headers, json={
                    "model": self.model, "max_tokens": self.max_tokens, "system": system,
                    "messages": messages, "tools": tools, "stream": True}) as response:
                response.raise_for_status()
                async for raw in response.aiter_lines():
                    if not raw.startswith("data:"):
                        continue
                    payload = raw[5:].strip()
                    if payload in {"", "[DONE]"}:
                        continue
                    event = json.loads(payload)
                    kind = event.get("type")
                    if kind == "content_block_start":
                        index = event.get("index", 0)
                        block = event.get("content_block") or {}
                        if block.get("type") == "text":
                            blocks[index] = {"type": "text", "text": block.get("text", "")}
                        elif block.get("type") == "tool_use":
                            blocks[index] = {"type": "tool_use", "id": block.get("id"),
                                             "name": block.get("name"), "input": block.get("input") or {},
                                             "_partial": ""}
                        else:
                            blocks[index] = {"type": block.get("type", "unknown")}
                    elif kind == "content_block_delta":
                        index = event.get("index", 0)
                        delta = event.get("delta") or {}
                        block = blocks.setdefault(index, {"type": "text", "text": ""})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            block["text"] = block.get("text", "") + text
                            if on_text and text:
                                on_text(text)
                        elif delta.get("type") == "input_json_delta":
                            block["_partial"] = block.get("_partial", "") + delta.get("partial_json", "")
                    elif kind == "content_block_stop":
                        block = blocks.get(event.get("index", 0), {})
                        if block.get("type") == "tool_use":
                            partial = block.pop("_partial", "")
                            if partial:
                                try:
                                    parsed = json.loads(partial)
                                except ValueError as exc:
                                    raise ValueError("工具参数不是完整 JSON") from exc
                                if not isinstance(parsed, dict):
                                    raise ValueError("工具参数需要 JSON 对象")
                                block["input"] = parsed
                            block.pop("_partial", None)
                    elif kind == "message_delta":
                        stop_reason = (event.get("delta") or {}).get("stop_reason") or stop_reason
                    elif kind == "error":
                        detail = event.get("error") or {}
                        raise ValueError(f"模型流式响应错误：{detail.get('message') or detail}")
        except httpx.HTTPStatusError as exc:
            raise ValueError(self._http_error(exc)) from exc
        except httpx.RequestError as exc:
            raise ValueError(f"模型请求未完成（{type(exc).__name__}）") from exc
        content = []
        for index in sorted(blocks):
            block = dict(blocks[index])
            block.pop("_partial", None)
            if block.get("type") in {"text", "tool_use"}:
                content.append(block)
        return {"content": content, "stop_reason": stop_reason}

    async def agentloop(self, task: Task, environment: dict, messages: list, prompt: str, max_turns: int,
                        checkpoint, on_text=None, context_manager=None):
        """Advance one Messages task until the model returns final text or exhausts its budget."""
        async with AsyncExitStack() as resources:
            remote = RemoteTools(task.store, task.mcp_servers, resources)
            # Reconnect and rediscover when a follow-up starts a new session.
            task.tools.active = {k: v for k, v in task.tools.active.items() if not k.startswith("mcp_")}
            checked_memory = None
            for _ in range(max_turns):
                used = {r["entry_id"]: r["revision"] for r in task.receipts if r.get("ok") and "entry_id" in r}
                if used:
                    version = file_version(task.store.path), task.store.memory.fingerprint(), used
                    if version != checked_memory:
                        changed = task.store.changed_revisions(used)
                        if changed:
                            environment["changed_memory"] = changed
                        else:
                            environment.pop("changed_memory", None)
                        checked_memory = version
                context = task.instructions(environment)
                if task.review_requested:
                    context += "\n请对照原始目标与已有证据复核方向，必要时修正下一步。"
                    task.review_requested = False
                tools_now = list(task.tools.active.values())
                request_messages = messages
                if context_manager is not None:
                    before = context_manager.compactions
                    request_messages = await context_manager.view(context, messages, tools_now)
                    if context_manager.compactions != before:
                        task.compactions += context_manager.compactions - before
                if on_text is None:
                    data = await self.send(context, request_messages, tools_now)
                else:
                    data = await self.stream_send(context, request_messages, tools_now, on_text)
                blocks = data["content"]
                if any(not isinstance(b, dict) for b in blocks):
                    raise ValueError("无效的模型消息块")
                messages.append({"role": "assistant", "content": blocks})
                calls = [b for b in blocks if b.get("type") == "tool_use"]
                stop = data.get("stop_reason")
                if stop in {"end_turn", "stop_sequence"} and not calls:
                    answer = "\n".join(b["text"] for b in blocks if b.get("type") == "text")
                    if not answer.strip():
                        raise ValueError("模型已结束回合，但没有返回文本结果")
                    return answer, messages
                if stop != "tool_use" or not 1 <= len(calls) <= 32:
                    raise ValueError(f"模型回复未完成，停止原因 {stop!r}")
                used = {entry["id"] for entry in task.receipts}
                for call in calls:
                    ident = call.get("id")
                    if (not isinstance(ident, str) or not ident or ident in used
                            or not isinstance(call.get("name"), str) or not isinstance(call.get("input"), dict)):
                        raise ValueError("工具调用标识或参数无效")
                    used.add(ident)
                if all(c["name"] in {"list_files", "read_file", "recall"} for c in calls):
                    results = await asyncio.gather(*(task._tool_result(c, remote) for c in calls))
                else:
                    results = [await task._tool_result(c, remote) for c in calls]
                observations = {"role": "user", "content": results}
                summaries = [c["input"] for c, r in zip(calls, results)
                             if c["name"] == "compact_context" and not r["is_error"]]
                if summaries:
                    goal = task.goal if task.goal == prompt else [
                        {"type": "text", "text": task.goal}, {"type": "text", "text": prompt}]
                    # The assistant's tool_use includes its summary. Keep its paired results intact.
                    messages = [{"role": "user", "content": goal}, messages[-1], observations]
                    task.compactions += 1
                    if checkpoint is not None:
                        checkpoint(summaries[-1])
                else:
                    messages.append(observations)
            raise ValueError(f"已达到本次任务的 {max_turns} 轮预算")


@dataclass
class Task:
    store: Store
    writable: bool = False
    exec_allowed: bool = False
    network_allowed: bool = True
    approval: Callable[[str, dict], Awaitable[bool]] | None = None
    workspace: Path | None = None
    allow_workers: bool = False
    worker_limit: int = 2
    worker_callback: Callable[[dict], None] | None = None
    activity_callback: Callable[[str], None] | None = None
    id: str = field(default_factory=lambda: uuid4().hex)
    entry: str = "run"
    host: str | None = None
    mcp_servers: tuple[str, ...] = ()
    agent_edit: str | None = None
    agent_revision: str | None = field(default=None, init=False)
    goal: str | None = field(default=None, init=False, repr=False)
    compactions: int = field(default=0, init=False)
    executor_name: str | None = field(default=None, init=False)
    review_requested: bool = field(default=False, init=False, repr=False)
    status: str = field(default="queued", init=False)
    answer: str = field(default="", init=False)
    error: str = field(default="", init=False)
    warning: str = field(default="", init=False)
    receipts: list = field(default_factory=list, init=False)
    history: list = field(default_factory=list, init=False)
    artifacts: dict = field(default_factory=dict, init=False)
    worker_tasks: dict = field(default_factory=dict, init=False)
    provider: object | None = field(default=None, init=False, repr=False)
    max_turns: int = field(default=12, init=False)
    timeout: int = field(default=180, init=False)

    def __post_init__(self):
        if self.entry == "dream":
            self.writable, self.exec_allowed, self.agent_edit, self.mcp_servers = False, False, None, ()
            self.allow_workers, self.workspace = False, None

    @cached_property
    def tools(self):
        tools = Tools(self.store, self.id, writable=self.writable, agent_edit=self.agent_edit,
                      read_only=self.entry == "dream", exec_allowed=self.exec_allowed,
                      network_allowed=self.network_allowed,
                      workspace=self.workspace, allow_workers=self.allow_workers)
        if self.mcp_servers:
            fields = DISCOVER["input_schema"]["properties"] | {
                "server": {"type": "string", "enum": list(self.mcp_servers)}}
            tools.active["discover"] = tool("discover", DISCOVER["description"] +
                " 查外部工具时传 kind=tool 和已授权的 MCP server。", fields, ("kind",))
        return tools

    def result(self) -> dict:
        return {"task_id": self.id, "status": self.status, "answer": self.answer,
                "error": self.error, "warning": self.warning, "receipts": list(self.receipts),
                "agent_revision": self.agent_revision, "compactions": self.compactions, "executor": self.executor_name}

    def instructions(self, environment: dict) -> str:
        # Read at the request boundary. An in-flight reply keeps its original tools and receipts.
        definition = self.store.load_agent()
        self.agent_revision = skill_revision(definition)
        environment["agent_revision"] = self.agent_revision
        environment["agent_path"] = str(self.store.agent_file)
        return (definition + "\n本地环境（JSON 数据）。文件工具以 project_root 为根。\n"
                + json.dumps(environment, ensure_ascii=False, separators=(",", ":")))

    async def _tool_result(self, call: dict, remote: RemoteTools) -> dict:
        name, values = call["name"], call["input"]
        if self.activity_callback:
            self.activity_callback(name)
        discovery = name == "discover" and "server" in values
        external = discovery or name in remote.selected

        async def execute():
            receipt = {"id": call["id"], "tool": name}
            try:
                if self.approval is not None and name in APPROVAL_TOOLS:
                    if not await self.approval(name, values):
                        raise PermissionError("用户拒绝了这次操作")
                if discovery:
                    validate_arguments(self.tools.active[name], values)
                    if values["kind"] != "tool":
                        raise ValueError("MCP 服务只接受工具检索")
                    output = await remote.discover(values["server"], values.get("query", ""), self.tools.active)
                elif name in remote.selected:
                    output = await remote.call(name, values)
                elif name == "delegate":
                    validate_arguments(self.tools.active[name], values)
                    output = await self.delegate(values["tasks"])
                elif name == "accept_artifact":
                    validate_arguments(self.tools.active[name], values)
                    output = await asyncio.to_thread(self.accept_artifact, **values)
                else:
                    output = await asyncio.to_thread(self.tools.execute, name, values)
                receipt["ok"] = True
                if name in ("list_files", "read_file", "write_file", "search_files", "edit_file"):
                    receipt["path"] = values.get("path", ".")
                if name in ("read_file", "write_file", "edit_file"):
                    receipt["sha256"] = output["sha256"]
                if name == "search_files":
                    receipt["matches"] = len(output["results"])
                if name == "run_command":
                    receipt["exit_code"] = output["exit_code"]
                    receipt["timed_out"] = output["timed_out"]
                if name == "web_search":
                    receipt["results"] = len(output["results"])
                if name == "web_fetch":
                    receipt["url"] = output["url"]
                    receipt["status"] = output["status"]
                if name == "delegate":
                    receipt["workers"] = len(output["workers"])
                    receipt["artifacts"] = len(output["artifacts"])
                if name == "accept_artifact":
                    receipt["path"] = output["path"]
                    receipt["sha256"] = output["sha256"]
                if name in ("recall", "remember"):
                    receipt.update(entry_id=output["id"], revision=output["revision"])
                if name == "revise_agent":
                    receipt["revision"] = output["revision"]
                if name in remote.selected:
                    receipt["server"], receipt["remote_tool"] = remote.selected[name][:2]
                content = json.dumps(output, ensure_ascii=False)
            except asyncio.CancelledError:
                self.receipts.append(receipt | {"ok": False, "state": "result_unknown"})
                raise
            except Exception as exc:
                receipt["ok"] = False
                content = str(exc)[:500] or type(exc).__name__
            self.receipts.append(receipt)
            return {"type": "tool_result", "tool_use_id": call["id"],
                    "content": content, "is_error": not receipt["ok"]}

        # MCP sessions enter and exit their async contexts in the owning task.
        if external:
            return await execute()
        # Once a local write has begun, obtain its receipt before reporting cancellation.
        pending = asyncio.create_task(execute())
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            await pending
            raise

    async def run(self, prompt: str, provider: Messages | Native | Callable[[], Messages | Native],
                  *, max_turns: int = 12, timeout: int = 180,
                  checkpoint=None, on_text=None, context_manager=None):
        self.status, self.answer, self.error = "running", "", ""
        messages = [*self.history, {"role": "user", "content": prompt}]
        try:
            if callable(provider):
                provider = provider()
            self.executor_name = "native" if isinstance(provider, Native) else "messages"
            if not prompt.strip():
                raise ValueError("任务内容不能为空")
            self.provider, self.max_turns, self.timeout = provider, max_turns, timeout
            if self.goal is None:
                self.goal = prompt
            environment = inspect_environment(self.store, self.entry, self.host, self.writable,
                                              self.mcp_servers, agent_edit=self.agent_edit,
                                              exec_allowed=self.exec_allowed,
                                              network_allowed=self.network_allowed)
            if isinstance(provider, Native):
                if any((self.writable, self.mcp_servers, self.agent_edit, self.store.confirm_shared)):
                    raise ValueError("本次带有本地工具授权，请使用 Messages 模式，或在原生宿主中授予所需权限")
                environment["execution"] = "native_runner"
                environment["grants"] = {"enforced_by": "native_host", "project": str(self.store.project)}
                response = provider.finish(self.store, self.instructions(environment), messages)
                self.answer = await asyncio.wait_for(response, timeout)
                self.history = [*messages, {"role": "assistant", "content": self.answer}]
            else:
                kwargs = {"on_text": on_text} if on_text is not None else {}
                if context_manager is not None:
                    kwargs["context_manager"] = context_manager
                turns = provider.agentloop(self, environment, messages, prompt, max_turns, checkpoint, **kwargs)
                self.answer, self.history = await asyncio.wait_for(turns, timeout)
            self.status = "completed"
        except asyncio.CancelledError:
            self.status = "cancelled"
            try:
                self.tools.cancel_commands()
            except OSError:
                pass
            raise
        except Exception as exc:
            # An executor failure belongs to this task; other tasks may still be running.
            self.status = "failed"
            self.error = str(exc) or type(exc).__name__
        finally:
            try:
                self.store.audit(self.id, self.status, len(self.receipts))
            except OSError as exc:
                self.warning = f"本次运行日志未写入实例目录：{exc}"

    async def delegate(self, tasks: list[str]) -> dict:
        from .workers import delegate as run_delegate
        if self.provider is None:
            raise ValueError("任务尚未开始，不能委派 worker")
        return await run_delegate(self, tasks, self.provider)

    def accept_artifact(self, artifact_id: str, path: str, expected: str) -> dict:
        from .workers import accept_artifact as accept
        return accept(self, artifact_id, path, expected)

    def cancel_worker(self, ident: str) -> bool:
        handle = self.worker_tasks.get(ident)
        if handle is None:
            return False
        handle.cancel()
        return True

    agentloop = run  # Compatibility for earlier Python callers.
