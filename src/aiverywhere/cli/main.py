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
import threading
import time
from pathlib import Path

from .. import __version__
from ..core import background
from ..core.dream import dream as run_dream, has_clues
from ..core.agent import Messages, Native, Task, executor
from ..platform.environment import inspect_environment
from ..core.store import Store, instance_root, skill_text
from ..core.session import Session, SessionStore
from ..core.context import ContextManager


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
    root.add_argument("--new", dest="new_session", action="store_true", help="开始新的 CLI session（默认恢复最近 session）")
    root.add_argument("--allow-write", dest="root_allow_write", action="store_true",
                      help="交互式 CLI 允许写入项目文件（也可用 aiverywhere chat --allow-write）")
    root.add_argument("--allow-exec", dest="root_allow_exec", action="store_true",
                      help="交互式 CLI 允许执行命令（也可用 aiverywhere chat --allow-exec）")
    root.add_argument("--ask-permissions", dest="root_ask_permissions", action="store_true",
                      help="交互式 CLI 对写文件和命令逐次询问")
    root.add_argument("--no-network", dest="root_no_network", action="store_true",
                      help="交互式 CLI 禁用 web_search/web_fetch")
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
    chat.add_argument("--new", dest="new_session", action="store_true", default=argparse.SUPPRESS, help="开始新的 CLI session")
    chat.add_argument("--ask-permissions", dest="ask_permissions", action="store_true",
                      default=argparse.SUPPRESS, help="对写文件和命令逐次询问")
    chat.add_argument("--no-network", dest="no_network", action="store_true",
                      default=argparse.SUPPRESS, help="禁用 web_search/web_fetch")
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


SLASH_COMMANDS = (
    ("/help", "显示帮助"),
    ("/new", "开始一个新的会话"),
    ("/resume", "恢复指定 session：/resume <id>"),
    ("/sessions", "列出当前项目的 session"),
    ("/status", "当前 session 和上下文预算"),
    ("/compact", "手动压实当前上下文"),
    ("/permissions", "查看本次 session 的授权"),
    ("/grant", "授予本 session 权限：/grant write|exec|network"),
    ("/revoke", "撤销本 session 权限：/revoke write|exec|network"),
    ("/approve", "允许当前待确认的工具操作"),
    ("/deny", "拒绝当前待确认的工具操作"),
    ("/jobs", "查看任务状态"),
    ("/cancel", "取消当前任务"),
    ("/ask", "向已完成任务追加问题：/ask <task-id> <问题>"),
    ("/quit", "退出交互"),
)


def _slash_matches(text: str) -> list[tuple[str, str]]:
    if not text.startswith("/"):
        return []
    return [(command, description) for command, description in SLASH_COMMANDS
            if command.startswith(text)]


def _start_terminal_reader(loop, queue) -> threading.Thread | None:
    """Use a prompt-toolkit completion menu when a real TTY is available."""
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.styles import Style
    except ImportError:
        return None

    class SlashCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            for command, description in _slash_matches(text):
                yield Completion(command, start_position=-len(text),
                                 display=command, display_meta=description)

    def worker():
        session = PromptSession(completer=SlashCompleter(),
                                complete_while_typing=True,
                                style=Style.from_dict({"prompt": "bold #22d3ee"}))
        while True:
            try:
                line = session.prompt("aiverywhere › ")
            except EOFError:
                line = "/quit"
            except KeyboardInterrupt:
                line = "/cancel"
            except Exception:
                # Never leave the foreground loop waiting on a dead reader.
                line = "/quit"
            try:
                loop.call_soon_threadsafe(queue.put_nowait, line)
            except RuntimeError:
                return
            if line == "/quit":
                return

    thread = threading.Thread(target=worker, name="aiverywhere-prompt", daemon=True)
    thread.start()
    return thread


async def chat(args, store: Store, provider) -> int:
    """Keep one foreground agent session and one Task for the whole conversation."""
    tasks: dict[str, Task] = {}
    sessions = SessionStore(store)
    session: Session | None = None
    manager: ContextManager | None = None
    task: Task | None = None

    def emit(**fields):
        output(fields, args.json)

    def message(text: str):
        emit(event="help", message=text)

    def select_provider():
        return provider() if callable(provider) else provider

    grants = {"write": bool(args.allow_write), "exec": bool(args.allow_exec),
              "network": not bool(getattr(args, "no_network", False))}
    ask = {"write": bool(getattr(args, "ask_permissions", False)) and not grants["write"],
           "exec": bool(getattr(args, "ask_permissions", False)) and not grants["exec"]}
    if ask["write"]:
        grants["write"] = True
    if ask["exec"]:
        grants["exec"] = True
    approval_future = None

    async def request_approval(tool: str, values: dict) -> bool:
        nonlocal approval_future
        capability = "exec" if tool == "run_command" else "write"
        if not ask.get(capability):
            return True
        if approval_future is not None and not approval_future.done():
            return False
        future = asyncio.get_running_loop().create_future()
        approval_future = future
        detail = json.dumps(values, ensure_ascii=False)[:700]
        message(f"权限请求 [{capability}] {tool}: {detail}\n输入 /approve 允许本次，或 /deny 拒绝。")
        try:
            allowed = await asyncio.wait_for(future, timeout=300)
        except asyncio.TimeoutError:
            allowed = False
            message("权限请求超时，已拒绝。")
        finally:
            approval_future = None
        if session is not None:
            try:
                session.append_permission(f"{capability}:{tool}", allowed, "approval")
            except (OSError, ValueError):
                pass
        return allowed

    def build_task(session_id: str, history: list) -> Task:
        result = Task(store, writable=grants["write"], exec_allowed=grants["exec"],
                      network_allowed=grants["network"],
                      entry="chat", host=args.host, mcp_servers=tuple(args.mcp),
                      agent_edit=args.agent_edit, allow_workers=True, id=session_id,
                      approval=request_approval if (ask["write"] or ask["exec"]) else None)
        result.history = history
        return result

    def resolve_approval(allowed: bool) -> None:
        if approval_future is not None and not approval_future.done():
            approval_future.set_result(allowed)
        else:
            message("当前没有待处理的权限请求。")

    async def execute(candidate: Task, prompt: str):
        streamed = False
        if not args.json and sys.stdout.isatty():
            def worker_event(event):
                action = f" · {event['action']}" if event.get("action") else ""
                print(f"\n[worker {event.get('id')}] {event.get('status')}{action}  {event.get('description', '')}",
                      file=sys.stderr, flush=True)
            candidate.worker_callback = worker_event

        def on_text(delta: str):
            nonlocal streamed
            if not delta:
                return
            streamed = True
            sys.stdout.write(delta)
            sys.stdout.flush()

        emit(event="accepted", task_id=candidate.id, status="queued")
        emit(event="start", task_id=candidate.id, status="running")
        try:
            await candidate.run(prompt, select_provider(), max_turns=args.max_turns,
                                timeout=args.timeout,
                                on_text=on_text if not args.json else None,
                                context_manager=manager)
        except asyncio.CancelledError:
            # Task.run has already recorded the cancelled status and audit row.
            pass
        finally:
            if streamed:
                print(flush=True)
        result = candidate.result()
        if streamed and not args.json:
            result = result | {"answer": ""}
        emit(event="result", **result)

    async def run_turn(candidate: Task, prompt: str):
        nonlocal current
        history_before = len(candidate.history)
        assert session is not None
        turn_id = session.begin_turn(prompt)
        try:
            await execute(candidate, prompt)
        except asyncio.CancelledError:
            candidate.status = "cancelled"
            raise
        except Exception as exc:
            candidate.status = "failed"
            candidate.error = str(exc) or type(exc).__name__
            raise
        finally:
            try:
                if candidate.status == "completed":
                    new_messages = candidate.history[history_before:]
                    session.finish_turn(turn_id, new_messages, candidate.answer,
                                        candidate.status)
                else:
                    session.fail_turn(turn_id, candidate.status, candidate.error)
            except (OSError, ValueError) as exc:
                candidate.warning = f"session 写入失败：{exc}"
                emit(event="help", message=candidate.warning)

    def open_session(*, new: bool = False, ident: str | None = None) -> Task:
        nonlocal session, manager, task
        previous = session
        candidate = None
        try:
            if ident is not None:
                candidate = sessions.open(ident)
                candidate.acquire()
            elif new:
                candidate = sessions.create()
            else:
                candidate = sessions.latest()
                if candidate is None:
                    candidate = sessions.create()
                else:
                    candidate.acquire()
            candidate.load()
            if candidate.resolve_pending():
                message(f"恢复 session {candidate.id}；上次回合结果未知，已记录待核对。")
            new_task = build_task(candidate.id, candidate.history())
            summary = candidate.summary()

            def persist_summary(text: str, method: str, covers: int):
                candidate.append_summary(text, method=method, covers_messages=covers)
                if not args.json:
                    message(f"context compacted（{method}，覆盖 {covers} 条消息；原始 session 保留）")

            new_manager = ContextManager(store, lambda: select_provider(), summary=summary,
                                         settings=store.session_settings(),
                                         on_summary=persist_summary)
            if previous is not None and previous is not candidate:
                previous.release()
            session = candidate
            task = new_task
            manager = new_manager
            tasks.clear()
            tasks[task.id] = task
            if not args.json:
                message(f"session {candidate.id} {'已恢复' if previous else '已开始'}")
            return task
        except Exception:
            if candidate is not None and candidate is not previous and candidate._lock is not None:
                candidate.release()
            raise

    help_text = ("多轮会话：每行续接当前 session，输入 / 显示命令菜单。"
                 "/help 帮助、/new 新会话、/resume 恢复、/sessions 列表、"
                 "/compact 压实、/permissions 权限、/grant 或 /revoke 授权、"
                 "/approve 或 /deny 处理权限请求、/status 状态、"
                 "/jobs 任务、/cancel 取消、/ask 追问、/quit 退出。")

    def prompt():
        if sys.stdin.isatty() and not sys.stdin.closed:
            start = "" if os.environ.get("NO_COLOR") else "\033[1;36m"
            end = "" if not start else "\033[0m"
            print(start + "aiverywhere › " + end, end="", flush=True)

    queue: asyncio.Queue[str] = asyncio.Queue()
    pending: list[str] = []
    loop = asyncio.get_running_loop()
    terminal_thread = None
    if sys.stdin.isatty() and not args.json:
        terminal_thread = _start_terminal_reader(loop, queue)

    async def read_lines():
        async for raw in input_lines():
            await queue.put(raw)

    reader = None if terminal_thread is not None else asyncio.create_task(read_lines())
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
        open_session(new=bool(getattr(args, "new_session", False)))
        while not quitting:
            if terminal_thread is None:
                prompt()
            raw = pending.pop(0) if pending else await queue.get()
            line = raw.strip()
            if not line:
                continue
            if line == "/quit":
                break
            if line == "/cancel":
                if current is not None and not current.done():
                    current.cancel()
                else:
                    message("当前没有正在运行的任务。")
                continue
            if line == "/help":
                message(help_text)
                continue
            if line == "/new":
                if current is not None and not current.done():
                    message("当前任务仍在运行；先 /cancel，再开始新会话。")
                else:
                    try:
                        open_session(new=True)
                    except (OSError, ValueError) as exc:
                        message(f"开始新 session 失败：{exc}")
                continue
            if line == "/resume":
                message("用法：/resume <session-id>")
                continue
            if line.startswith("/resume "):
                if current is not None and not current.done():
                    message("当前任务仍在运行；先 /cancel，再恢复会话。")
                else:
                    ident = line.split(maxsplit=1)[1].strip()
                    try:
                        open_session(ident=ident)
                    except (OSError, ValueError) as exc:
                        message(f"恢复 session 失败：{exc}")
                continue
            if line == "/sessions":
                rows = sessions.list()
                if not rows:
                    message("当前项目还没有 session。")
                else:
                    text = "\n".join(
                        f"{row['id']}  turns={row['turns']}  {'pending' if row['pending'] else ''}  "
                        f"summary={row['summary_method'] or '-'}" for row in rows[:20])
                    message(text)
                continue
            if line == "/status":
                assert session is not None and task is not None and manager is not None
                info = session.info()
                tokens = manager.estimate(task.instructions({}), task.history,
                                          list(task.tools.active.values()))
                message(f"session={info['id']} turns={info['turns']} pending={info['pending']} "
                        f"summary={info['summary_method'] or '-'} tokens~{tokens}/{manager.max_tokens} "
                        f"write={grants['write']} exec={grants['exec']} network={grants['network']}")
                continue
            if line == "/compact":
                if current is not None and not current.done():
                    message("当前任务仍在运行；完成或取消后再压实。")
                elif task is None or manager is None:
                    message("当前没有可压实的会话。")
                else:
                    try:
                        await manager.force(task.instructions({}), task.history,
                                            list(task.tools.active.values()))
                        message("当前上下文已压实；原始 session 记录保留。")
                    except (OSError, ValueError) as exc:
                        message(f"压实失败：{exc}")
                continue
            if line == "/permissions":
                for capability in ("write", "exec", "network"):
                    state = "allowed" if grants[capability] else "denied"
                    if ask.get(capability):
                        state += " (ask each time)"
                    message(f"{capability}: {state}")
                continue
            if line.startswith("/grant") or line.startswith("/revoke"):
                command, _, capability = line.partition(" ")
                capability = capability.strip()
                if capability not in {"write", "exec", "network"}:
                    message("用法：/grant write|exec|network 或 /revoke write|exec|network")
                    continue
                if current is not None and not current.done():
                    message("当前任务仍在运行；完成或取消后再修改授权。")
                    continue
                allowed = command == "/grant"
                grants[capability] = allowed
                ask[capability] = False
                if task is None:
                    message("当前没有会话。")
                    continue
                if session is not None:
                    try:
                        session.append_permission(capability, allowed, "user")
                    except (OSError, ValueError) as exc:
                        message(f"权限审计写入失败：{exc}")
                task = build_task(session.id, task.history)
                tasks.clear()
                tasks[task.id] = task
                message(f"{capability}: {'已授权本 session' if allowed else '已撤销'}")
                continue
            if line == "/jobs":
                for candidate in tasks.values():
                    emit(event="status", task_id=candidate.id, status=candidate.status)
                continue
            target: Task | None = None
            if line.startswith("/"):
                cmd, _, rest = line.partition(" ")
                ident, _, followup = rest.partition(" ")
                target = tasks.get(ident)
                if cmd == "/ask" and target and followup.strip():
                    task_handle = asyncio.create_task(run_turn(target, followup))
                else:
                    message(help_text)
                    continue
            else:
                assert task is not None
                target = task
                task_handle = asyncio.create_task(run_turn(target, line))
            current = task_handle
            while True:
                getter = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({task_handle, getter},
                                             return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    incoming = getter.result().strip()
                    if incoming in {"/approve", "/deny"}:
                        resolve_approval(incoming == "/approve")
                    elif incoming == "/cancel":
                        task_handle.cancel()
                    elif incoming.startswith("/cancel "):
                        ident = incoming.split(maxsplit=1)[1].strip()
                        if not target.cancel_worker(ident):
                            message(f"没有找到 worker {ident}。")
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
        if session is not None:
            session.release()
        if reader is not None:
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


def welcome_chat(store: Store, new_session: bool = False, allow_write: bool = False,
                 allow_exec: bool = False, ask_permissions: bool = False,
                 no_network: bool = False) -> int:
    import httpx

    defaults = store.defaults()
    args = argparse.Namespace(command="chat", json=False, allow_write=allow_write,
                              max_turns=defaults["max_turns"], timeout=defaults["timeout"],
                              host=None, mcp=[], agent_edit=None, model=None, allow_exec=allow_exec,
                              new_session=new_session, ask_permissions=ask_permissions,
                              no_network=no_network)

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
            if launched and initialized:
                try:
                    configured = bool(store.configuration().get("model"))
                except (OSError, ValueError):
                    configured = False
                if not sys.stdin.isatty():
                    print("  提示：当前 stdin 不是终端；交互输入请直接在真实终端运行 aiverywhere，"
                          "或使用 aiverywhere chat。", flush=True)
                elif configured or os.getenv("AIVERYWHERE_MODEL") or os.getenv("ANTHROPIC_MODEL"):
                    return welcome_chat(store, getattr(args, "new_session", False),
                                        getattr(args, "root_allow_write", False),
                                        getattr(args, "root_allow_exec", False),
                                        getattr(args, "root_ask_permissions", False),
                                        getattr(args, "root_no_network", False))
                else:
                    print("  aiverywhere › 尚未配置 CLI 模型；运行 aiverywhere setup 后再对话。", flush=True)
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
