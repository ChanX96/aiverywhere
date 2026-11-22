"""Python CLI shared by a host skill, a terminal, and an external scheduler."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import signal
from contextlib import suppress
import json
import os
import stat
import sys
import time
from pathlib import Path

from .. import __version__
from ..core import background
from ..core.dream import dream as run_dream, has_clues
from ..core.agent import Messages, Native, Task, executor
from ..platform.environment import inspect_environment
from ..core.store import Store, instance_root, skill_text


def positive(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("请输入正整数")
    return number


def revision(value: str) -> str:
    value = value.lower()
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise argparse.ArgumentTypeError("请提供 skill --info 返回的 SHA-256 修订号")
    return value


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="aiverywhere", description="按需运行的个人 agent")
    root.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    root.add_argument("--home", type=Path, help="可写的 aiverywhere 安装根目录（或 AIVERYWHERE_HOME）")
    root.add_argument("--project", type=Path, default=Path.cwd(), help="绑定该任务的工作目录")
    root.add_argument("--host", help="由调用者声明的宿主名称，可省略")
    root.add_argument("--confirm-shared", action="store_true", help="用户已同意本次使用共用技能")
    sub = root.add_subparsers(dest="command")
    sub.add_parser("welcome", help="显示欢迎屏；直接运行 aiverywhere 会显示并进入交互")
    sub.add_parser("init", help="在安装根 data/ 中准备活动 agent 和统一配置，保留已有数据")
    setup = sub.add_parser("setup", help="交互或非交互地写入模型与运行参数")
    setup.add_argument("--no-input", action="store_true", help="不提问，使用参数、环境变量和默认值")
    setup.add_argument("--model", help="模型名称（或 AIVERYWHERE_MODEL / ANTHROPIC_MODEL）")
    setup.add_argument("--base-url", help="Messages 端点（默认 https://api.anthropic.com）")
    credentials = setup.add_mutually_exclusive_group()
    credentials.add_argument("--api-key", help="x-api-key 凭据；也可使用 ANTHROPIC_API_KEY")
    credentials.add_argument("--auth-token", help="Bearer 凭据；也可使用 ANTHROPIC_AUTH_TOKEN")
    credentials.add_argument("--api-key-env", help="读取 x-api-key 的环境变量名")
    credentials.add_argument("--auth-token-env", help="读取 Bearer 凭据的环境变量名")
    setup.add_argument("--max-tokens", type=positive, help="单次模型请求的最大输出 token（默认 4096）")
    setup.add_argument("--max-turns", type=positive, help="工具回合上限（默认 12）")
    setup.add_argument("--timeout", type=positive, help="单任务秒数（默认 180）")
    setup.add_argument("--port", type=int, choices=range(0, 65536), metavar="0-65535",
                       help="本地工作台端口（默认 8765）")
    link = sub.add_parser("link", help="把活动 agent 链接到项目的通用技能目录，供任意宿主读取")
    link.add_argument("--dir", type=Path, help="技能目录（默认 .agents/skills/aiverywhere）")
    web = sub.add_parser("web", help="在本机浏览与管理项目资料")
    web.add_argument("--port", default=None, type=int, help="本机端口，0 表示自动分配（默认 8765 或配置值）")
    browser = web.add_mutually_exclusive_group()
    browser.add_argument("--open", dest="open_browser", action="store_const", const="always",
                         help="启动后强制尝试打开浏览器")
    browser.add_argument("--no-open", dest="open_browser", action="store_const", const="never",
                         help="只打印地址，不打开浏览器")
    web.set_defaults(open_browser="auto")
    skill = sub.add_parser("skill", help="读取或修订宿主与 CLI 共用的 SKILL.md")
    publication = skill.add_mutually_exclusive_group()
    publication.add_argument("--info", action="store_true", help="准备实例活动文件，输出路径及内容修订号")
    publication.add_argument("--update", metavar="REV", type=revision, help="从标准输入发布完整文件，核对旧修订")
    sub.add_parser("env", help="只读查看本地运行环境、已授权范围和未验证能力")
    run = sub.add_parser("run", help="执行一次任务，可由宿主委派")
    run.add_argument("prompt", help="任务内容；传 - 可从标准输入读取")
    run.add_argument("--task-id", help="宿主分配的请求 ID，同一项目的重复请求返回已有回执")
    chat = sub.add_parser("chat", help="交互式 CLI，一次推进一个前台任务，可 /cancel")
    for command in (run, chat):
        command.add_argument("--model", help="Anthropic 兼容端点的模型名（或 AIVERYWHERE_MODEL）")
        command.add_argument("--mcp", action="append", default=[], metavar="NAME",
                             help="授权 config.json 的 mcpServers 中的服务，可重复指定")
        command.add_argument("--allow-write", action="store_true", help="允许写入和局部修改绑定项目的文本文件")
        command.add_argument("--allow-exec", action="store_true", help="允许在绑定项目中执行命令")
        command.add_argument("--allow-agent-edit", dest="agent_edit", metavar="REV", type=revision,
                             help="授权模型修订指定版本的实例工作约定")
        command.add_argument("--max-turns", type=positive, default=None,
                             help="裸 Messages 的模型回合上限（默认 12 或配置值）")
        command.add_argument("--timeout", type=positive, default=None, help="每个任务的总秒数（默认 180 或配置值）")
        command.add_argument("--json", action="store_true", help="输出机器可读的回执")

    mem = sub.add_parser("memory", help="按当前项目保存和找回经验")
    ops = mem.add_subparsers(dest="op", required=True)
    put = ops.add_parser("put", help="保存条目；更新时提供现行修订号")
    put.add_argument("title")
    put.add_argument("text")
    put.add_argument("--revision", type=positive)
    search = ops.add_parser("search", help="按线索查摘要；省略 query 可列当前种类")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--cold", action="store_true")
    for action in (put, search):
        action.add_argument("--kind", choices=("fact", "skill", "clue"), default="fact")
    for name in ("get", "forget"):
        ops.add_parser(name).add_argument("id")
    share = ops.add_parser("share", help="将核对过的通用技能用于同一用户的其他项目")
    share.add_argument("id")
    share.add_argument("--revision", type=positive, required=True)
    share.add_argument("--evidence", required=True)
    ops.add_parser("policy", help="设置跨项目技能确认偏好").add_argument("value", choices=("ask", "allow"))

    schedule = sub.add_parser("schedule", help="管理本项目的预授权计划").add_subparsers(dest="op", required=True)
    add = schedule.add_parser("add", help="登记一次、每日或每周任务")
    add.add_argument("prompt")
    add.add_argument("--at", required=True, help="ISO 日期时间，带偏移或与 --timezone 合用")
    add.add_argument("--timezone", help="IANA 时区，如 Asia/Shanghai")
    add.add_argument("--repeat", choices=("once", "daily", "weekly"), default="once")
    add.add_argument("--grace", type=positive, default=60, help="正常触发的允许延迟（秒）")
    add.add_argument("--model")
    add.add_argument("--mcp", action="append", default=[])
    add.add_argument("--allow-write", action="store_true")
    schedule.add_parser("list", help="查看计划与下一次执行时间")
    schedule.add_parser("disable", help="停用后续执行").add_argument("id")
    schedule.add_parser("results", help="查看已认领的本项目任务及产物回执")
    schedule.add_parser("notices", help="展示错过的任务和异常提醒")
    wake = sub.add_parser("wake", help="由外部调度器调用一次：到期计划、微信任务和可选 Dream")
    wake.add_argument("--dream", action="store_true", help="有线索时执行一次普通 Dream")
    wake.add_argument("--model", help="Dream 使用的模型；计划沿用创建时的模型配置")
    dream = sub.add_parser("dream", help="执行一次空闲 Dream，处理待处理的 memory 线索")
    dream.add_argument("--note", help="只记录一条线索，等价于 memory put --kind clue")
    dream.add_argument("--model")
    wechat = sub.add_parser("wechat", help="可信网关递交微信消息或查询简短进度")
    wechat.add_argument("--status", metavar="TASK_ID", help="查询任务状态、答复和渠道回执")
    return root


def memory(args, store: Store):
    if args.op == "put":
        return store.remember(args.title, args.text, args.kind, "user", revision=args.revision)
    if args.op == "search":
        return store.search(args.query, args.kind, cold=args.cold, limit=20 if args.kind == "clue" else 5)
    if args.op == "get":
        return store.recall(args.id)
    if args.op == "forget":
        store.forget(args.id)
        return {"deleted": args.id}
    if args.op == "share":
        return store.share(args.id, args.revision, args.evidence)
    with store.edit() as state:
        state["shared_policy"] = args.value
    return {"shared_policy": args.value}


def output(event: dict, as_json: bool):
    if as_json:
        print(json.dumps(event, ensure_ascii=False), flush=True)
    else:
        label = " ".join(str(event[k]) for k in ("task_id", "status") if k in event)
        body = event.get("answer") or event.get("error") or event.get("message", "")
        print(" ".join(s for s in (f"[{label}]" if label else "", body) if s), flush=True)
        if event.get("warning"):
            print(event["warning"], file=sys.stderr, flush=True)


def print_json(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def schedule_command(args, store: Store):
    if args.op == "add":
        print_json(background.add_plan(store, args))
    elif args.op == "list":
        print_json([background.plan_info(p) for p in background.plans(store)])
    elif args.op == "disable":
        background.disable(store, args.id)
        print_json({"disabled": args.id})
    elif args.op == "results":
        print_json([r for r in store.snapshot(runtime_only=True).get("runs", {}).values()
                    if r["project"] == str(store.project)])
    else:
        background.show_notices(store, print_json)


async def wake_command(args, store: Store, client) -> int:
    """Process due plans, one WeChat job, and optionally one Dream, then exit."""
    from ..core import background
    from ..integrations import wechat

    failed = False
    while True:
        batch = background.claim_due(store, time.time(), 1)
        if not batch:
            break
        for ident, plan in batch:
            result = await background.execute_plan(store, ident, plan, client, args.host)
            print_json(result)
            failed |= result["status"] != "completed"
    key = wechat.next_job(store)
    if key:
        result = await wechat.process(store, client, key)
        if result.get("status") not in {"idle", "busy"}:
            print_json(result)
        failed |= result.get("delivery") in {"unknown", "verify", "rejected"}
    if args.dream and has_clues(store):
        result = await run_dream(store, client=client, model=args.model, host=args.host)
        if result.get("status") not in {"idle", "busy"}:
            print_json(result)
        failed |= result.get("status") == "failed"
    return int(failed)


async def input_lines():
    """On a terminal or pipe, keep the event loop responsive while awaiting input."""
    fd = sys.stdin.fileno()
    if not sys.stdin.isatty() and not stat.S_ISFIFO(os.fstat(fd).st_mode):
        for line in sys.stdin:
            yield line
        return
    reader = asyncio.StreamReader()
    pipe = os.fdopen(os.dup(fd), "rb", buffering=0)
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), pipe)
    try:
        while line := await reader.readline():
            yield line.decode()
    finally:
        transport.close()


async def chat(args, store: Store, provider) -> int:
    """Read one line, finish one task, then read the next. No queue or cancel state."""
    tasks: dict[str, Task] = {}

    def emit(**fields):
        output(fields, args.json)

    def select_provider():
        return provider() if callable(provider) else provider

    async def execute(task: Task, prompt: str):
        streamed = False
        if not args.json and sys.stdout.isatty():
            def worker_event(event):
                action = f" · {event['action']}" if event.get("action") else ""
                print(f"\n[worker {event.get('id')}] {event.get('status')}{action}  {event.get('description', '')}",
                      file=sys.stderr, flush=True)
            task.worker_callback = worker_event

        def on_text(delta: str):
            nonlocal streamed
            if not delta:
                return
            streamed = True
            sys.stdout.write(delta)
            sys.stdout.flush()

        emit(event="accepted", task_id=task.id, status="queued")
        emit(event="start", task_id=task.id, status="running")
        try:
            await task.run(prompt, select_provider(), max_turns=args.max_turns, timeout=args.timeout,
                           on_text=on_text if not args.json else None)
        except asyncio.CancelledError:
            # Task.run has already recorded the cancelled status and audit row.
            pass
        finally:
            if streamed:
                print(flush=True)
        result = task.result()
        if streamed and not args.json:
            result = result | {"answer": ""}
        emit(event="result", **result)

    help_text = "每行执行一个任务，完成后再读取下一行。/help 帮助，/jobs 状态，/cancel 取消当前任务，/quit 退出。"
    if sys.stdin.isatty():
        emit(event="help", message=help_text)

    def prompt():
        if sys.stdin.isatty():
            start = "" if os.environ.get("NO_COLOR") else "\033[1;36m"
            end = "" if not start else "\033[0m"
            print(start + "aiverywhere › " + end, end="", flush=True)

    queue: asyncio.Queue[str] = asyncio.Queue()
    pending: list[str] = []

    async def read_lines():
        async for raw in input_lines():
            await queue.put(raw)

    reader = asyncio.create_task(read_lines())
    loop = asyncio.get_running_loop()
    current: asyncio.Task | None = None
    quitting = False

    def interrupt():
        nonlocal current
        if current is not None and not current.done():
            current.cancel()
        else:
            raise KeyboardInterrupt

    try:
        loop.add_signal_handler(signal.SIGINT, interrupt)
    except (NotImplementedError, RuntimeError):
        pass
    try:
        while not quitting:
            prompt()
            raw = pending.pop(0) if pending else await queue.get()
            line = raw.strip()
            if not line:
                continue
            if line == "/quit":
                break
            if line == "/cancel":
                emit(event="help", message="当前没有正在运行的任务。")
                continue
            if line == "/help":
                emit(event="help", message=help_text)
                continue
            if line == "/jobs":
                for task in tasks.values():
                    emit(event="status", task_id=task.id, status=task.status)
                continue
            if line.startswith("/"):
                cmd, _, rest = line.partition(" ")
                ident, _, followup = rest.partition(" ")
                task = tasks.get(ident)
                if cmd == "/ask" and task and followup.strip():
                    task_handle = asyncio.create_task(execute(task, followup))
                else:
                    emit(event="help", message=help_text)
                    continue
            else:
                task = Task(store, writable=args.allow_write, exec_allowed=args.allow_exec,
                            entry="chat", host=args.host, mcp_servers=tuple(args.mcp),
                            agent_edit=args.agent_edit, allow_workers=True)
                tasks[task.id] = task
                task_handle = asyncio.create_task(execute(task, line))
            current = task_handle
            while True:
                getter = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({task_handle, getter},
                                             return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    incoming = getter.result().strip()
                    if incoming == "/cancel":
                        task_handle.cancel()
                    elif incoming.startswith("/cancel "):
                        ident = incoming.split(maxsplit=1)[1].strip()
                        if not task.cancel_worker(ident):
                            emit(event="help", message=f"没有找到 worker {ident}。")
                    elif incoming == "/quit":
                        task_handle.cancel()
                        quitting = True
                    elif incoming:
                        pending.append(incoming)
                    if task_handle not in done:
                        continue
                else:
                    getter.cancel()
                    with suppress(asyncio.CancelledError):
                        await getter
                try:
                    task_handle.result()
                except asyncio.CancelledError:
                    pass
                break
            current = None
    finally:
        current = None
        try:
            loop.remove_signal_handler(signal.SIGINT)
        except (NotImplementedError, RuntimeError):
            pass
        reader.cancel()
        with suppress(asyncio.CancelledError):
            await reader
    return 0


async def one(args, store: Store, provider: Messages | Native) -> int:
    prompt = sys.stdin.read() if args.prompt == "-" else args.prompt
    options = dict(writable=args.allow_write, exec_allowed=args.allow_exec,
                   entry="delegate" if args.host else "run", host=args.host,
                   mcp_servers=tuple(args.mcp), agent_edit=args.agent_edit, allow_workers=True)
    if args.task_id:
        if len(args.task_id) > 128 or not all(c.isalnum() or c in "-_." for c in args.task_id):
            raise ValueError("task-id 只支持最多 128 个字母、数字、点、连字符或下划线")
        task = Task(store, id=args.task_id, **options)
        key = json.dumps([str(store.project), task.id], ensure_ascii=False)
        identity = ["native", provider.argv, provider.pass_env] if isinstance(provider, Native) else [provider.model, provider.base]
        fields = [prompt, args.allow_write, args.allow_exec, args.mcp, store.confirm_shared, *identity,
                  args.host, args.max_turns, args.timeout]
        if args.agent_edit:
            fields.append(args.agent_edit)
        request = json.dumps(fields)
        signature = hashlib.sha256(request.encode()).hexdigest()
        with store.edit() as state:
            jobs = state.setdefault("jobs", {})
            if previous := jobs.get(key):
                if previous["signature"] != signature:
                    raise ValueError("同一 task-id 已绑定到其他请求")
                result = previous["result"]
                output(result, args.json)
                return 0 if result["status"] in {"running", "completed"} else 1
            task.status = "running"
            jobs[key] = {"project": str(store.project), "signature": signature, "result": task.result(),
                         "pid": os.getpid(), "expires": time.time() + args.timeout + 30}
    else:
        task = Task(store, **options)
    streamed = False

    def on_text(delta: str):
        nonlocal streamed
        if not delta:
            return
        streamed = True
        sys.stdout.write(delta)
        sys.stdout.flush()

    if not args.json and sys.stdout.isatty():
        def worker_event(event):
            action = f" · {event['action']}" if event.get("action") else ""
            print(f"\n[worker {event.get('id')}] {event.get('status')}{action}  {event.get('description', '')}",
                  file=sys.stderr, flush=True)
        task.worker_callback = worker_event
    handle = asyncio.create_task(task.run(
        prompt, provider, max_turns=args.max_turns, timeout=args.timeout,
        on_text=on_text if not args.json else None))
    loop = asyncio.get_running_loop()

    def interrupt():
        handle.cancel()

    try:
        loop.add_signal_handler(signal.SIGINT, interrupt)
    except (NotImplementedError, RuntimeError):
        pass
    try:
        await handle
    except asyncio.CancelledError:
        pass
    finally:
        try:
            loop.remove_signal_handler(signal.SIGINT)
        except (NotImplementedError, RuntimeError):
            pass
        if streamed:
            print(flush=True)
        if args.task_id:
            with store.edit() as state:
                state["jobs"][key]["result"] = task.result()
    result = task.result()
    if streamed and not args.json:
        result = result | {"answer": ""}
    output(result, args.json)
    return 0 if task.status == "completed" else 1


async def invoke(args, store: Store) -> int:
    import httpx

    defaults = store.defaults()
    for name in ("max_turns", "timeout"):
        if getattr(args, name, None) is None:
            setattr(args, name, defaults[name])
    async with httpx.AsyncClient(timeout=60) as client:
        if args.command == "wake":
            return await wake_command(args, store, client)
        if args.command == "dream":
            result = await run_dream(store, client=client, model=args.model, host=args.host)
            print_json(result)
            return int(result["status"] == "failed")
        def notify(items):
            if args.command == "run":
                print(json.dumps({"event": "notices", "items": items}, ensure_ascii=False), file=sys.stderr, flush=True)
            else:
                output({"event": "notices", "items": items,
                        "message": "待办提醒 " + json.dumps(items, ensure_ascii=False)}, args.json)
        background.show_notices(store, notify)
        if args.command == "chat":
            # A queued job or follow-up binds the current config only when its slot opens.
            return await chat(args, store, lambda: executor(client, args.model, store))
        return await one(args, store, executor(client, args.model, store))


def welcome_chat(store: Store) -> int:
    import httpx

    defaults = store.defaults()
    args = argparse.Namespace(command="chat", json=False, allow_write=False,
                              max_turns=defaults["max_turns"], timeout=defaults["timeout"],
                              host=None, mcp=[], agent_edit=None, model=None, allow_exec=False)

    async def run():
        async with httpx.AsyncClient(timeout=60) as client:
            return await chat(args, store, lambda: executor(client, args.model, store))

    return asyncio.run(run())


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    launched = args.command is None
    if launched:
        args.command = "welcome"
    try:
        passive = args.command in {"init", "env", "welcome"} or (args.command == "skill" and not (args.info or args.update))
        home = args.home or instance_root(required=not passive)
        if args.command == "skill" and not (args.info or args.update):
            print(skill_text(home), end="")
            return 0
        store = Store(home, args.project, confirm_shared=args.confirm_shared)
        if args.confirm_shared and args.command not in {"run", "memory"}:
            raise ValueError("--confirm-shared 仅适用于一次 run 或 memory 调用")
        if args.command == "welcome":
            from ..ui.welcome import show
            initialized = show(store)
            if launched and initialized and sys.stdin.isatty():
                try:
                    configured = bool(store.configuration().get("model"))
                except (OSError, ValueError):
                    configured = False
                if configured or os.getenv("AIVERYWHERE_MODEL") or os.getenv("ANTHROPIC_MODEL"):
                    return welcome_chat(store)
                print("  提示：尚未配置 CLI 模型，运行 aiverywhere setup 后再对话。", flush=True)
            return 0
        if args.command == "init":
            print_json(store.initialize())
            return 0
        if args.command == "setup":
            from ..core.configure import configure
            print_json(configure(
                store, no_input=args.no_input, model=args.model, base_url=args.base_url,
                api_key=args.api_key, auth_token=args.auth_token,
                api_key_env=args.api_key_env, auth_token_env=args.auth_token_env,
                max_tokens=args.max_tokens, max_turns=args.max_turns, timeout=args.timeout,
                port=args.port))
            return 0
        if args.command == "link":
            print_json(store.link_agent(args.dir))
            return 0
        if args.command == "web":
            from ..integrations.web.server import serve
            serve(store, args.port if args.port is not None else store.defaults()["port"],
                  getattr(args, "open_browser", "auto"))
            return 0
        if args.command == "skill":
            print_json(store.skill_info() if args.info else store.revise_agent(args.update, sys.stdin.read(65537)))
            return 0
        if args.command == "env":
            print(json.dumps(inspect_environment(store, "env", args.host, False, exec_allowed=False),
                             ensure_ascii=False, indent=2))
            return 0
        if args.command == "memory":
            print_json(memory(args, store))
            return 0
        if args.command == "wechat":
            from ..integrations.wechat import receive, status
            if args.status is not None:
                print_json(status(store, args.status))
                return 0
            envelope = sys.stdin.buffer.read(1_048_577)
            if len(envelope) > 1_048_576:
                raise ValueError("微信入站消息超过 1 MiB")
            print_json(receive(store, json.loads(envelope)))
            return 0
        if args.command == "schedule":
            schedule_command(args, store)
            return 0
        if args.command == "dream" and args.note is not None:
            text = " ".join(args.note.split())
            print_json(store.remember("线索：" + text[:80], text, "clue", "user"))
            return 0
        return asyncio.run(invoke(args, store))
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
