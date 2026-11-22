"""Task-local discovery and execution of the instance's capabilities."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import signal
import socket
import subprocess
import xml.etree.ElementTree as ElementTree
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

from .store import Store, atomic_write, normalized, skill_template


def _search_queries(query: str) -> list[str]:
    """RSS search often does worse with dates; try a short form as a second query."""
    short = re.sub(
        r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|"
        r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|"
        r"(今天|今日|明天|明日|后天|昨天|昨日|周[一二三四五六日天])",
        " ", query)
    short = re.sub(r"\s+", " ", short).strip()
    if short and short != query.strip():
        return [query, short]
    return [query]


def _rank_results(results: list[dict], query: str) -> list[dict]:
    terms = [term.casefold() for term in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", query)]
    def score(item):
        text = (item.get("title", "") + " " + item.get("content", "")).casefold()
        return sum(term in text for term in terms)
    return sorted(results, key=score, reverse=True)


def tool(name: str, description: str, properties: dict, required: tuple = ()) -> dict:
    return {"name": name, "description": description, "input_schema": {
        "type": "object", "properties": properties, "required": list(required),
        "additionalProperties": False,
    }}


TEXT = {"type": "string"}
INTEGER = {"type": "integer", "minimum": 0}
ARRAY = {"type": "array", "items": {"type": "string"}}
DISCOVER = tool("discover", "按需查找工具、项目事实、技能或待处理线索。查工具可用空查询；返回的工具可在下一轮调用。",
                {"kind": {"type": "string", "enum": ["tool", "fact", "skill", "clue"]},
                 "query": TEXT, "cold": {"type": "boolean"}}, ("kind",))
DELEGATE = tool("delegate", "并行委派 1–2 个独立子任务，每个 worker 在私有工作区完成 / delegate independent workers",
                {"tasks": ARRAY}, ("tasks",))
ACCEPT = tool("accept_artifact", "把 worker 产物复制到授权项目目标 / accept a worker artifact",
              {"artifact_id": TEXT, "path": TEXT, "expected": TEXT},
              ("artifact_id", "path", "expected"))
NATIVE = [
    tool("list_files", "列出项目目录中的文件和子目录 / list workspace directory",
         {"path": TEXT, "offset": INTEGER}),
    tool("read_file", "读取 UTF-8 文本文档或代码 / read project file, evidence",
         {"path": TEXT, "offset": INTEGER}, ("path",)),
    tool("write_file", "写入 UTF-8 文件 / write file. 创建传 expected=new，更新传读取到的 sha256。",
         {"path": TEXT, "text": TEXT, "expected": TEXT}, ("path", "text", "expected")),
    tool("search_files", "在项目文本中搜索字符串，返回路径、行号和片段 / search project text",
         {"query": TEXT, "path": TEXT, "limit": INTEGER}, ("query",)),
    tool("edit_file", "按旧哈希和唯一匹配片段做局部替换 / edit a unique fragment; never rewrite the whole file.",
         {"path": TEXT, "old": TEXT, "new": TEXT, "expected": TEXT},
         ("path", "old", "new", "expected")),
    tool("run_command", "在项目中执行一条命令，返回退出码和限长输出 / run argv in the workspace",
         {"argv": ARRAY, "cwd": TEXT, "timeout": INTEGER}, ("argv",)),
    tool("web_search", "搜索公开网页，返回标题、URL 和摘要。中文查询可用短关键词；年份/日期可能降低 RSS 召回 / search public web with a short query",
         {"query": TEXT}, ("query",)),
    tool("web_fetch", "读取公开 HTTP(S) 网页正文，拒绝内网地址 / fetch a public page",
         {"url": TEXT}, ("url",)),
    DELEGATE,
    ACCEPT,
    tool("remember", "保存一条持久事实、可复用技能或待处理线索 / save fact, skill or clue. 纠正旧条目时传 revision。",
         {"kind": {"type": "string", "enum": ["fact", "skill", "clue"]}, "title": TEXT, "text": TEXT,
          "revision": INTEGER}, ("kind", "title", "text")),
    tool("recall", "按 ID 展开已找到的记忆、技能或线索 / read memory, skill or clue",
         {"id": TEXT}, ("id",)),
    tool("clue_done", "标记一条已处理完的 Dream 线索 / resolve a reviewed clue",
         {"id": TEXT}, ("id",)),
    tool("share_skill", "供同一用户跨项目复用已验证的通用技能 / share verified skill. 先剔除客户资料再提供验证依据。",
         {"id": TEXT, "revision": INTEGER, "evidence": TEXT}, ("id", "revision", "evidence")),
    tool("used_skill", "核实本次成功复用后，刷新该版本技能的使用时间 / record verified use",
         {"id": TEXT, "revision": INTEGER, "evidence": TEXT}, ("id", "revision", "evidence")),
    tool("revise_agent", "发布实例工作约定。传保留原文件头的完整 SKILL.md，按调用方授权的旧修订校验。",
         {"text": TEXT}, ("text",)),
    tool("compact_context", "按已核实的进展压缩对话。确有偏离目标的证据时可带一句 concern / compact context",
         {"summary": TEXT, "concern": TEXT}, ("summary",)),
]


def validate_arguments(spec: dict, values: dict) -> None:
    schema = spec["input_schema"]
    if not isinstance(values, dict):
        raise ValueError("工具参数必须为对象")
    fields = schema["properties"]
    if set(schema["required"]) - values.keys() or values.keys() - fields.keys():
        raise ValueError(f"参数不匹配，请参照 {spec['name']} 的定义")
    types = {"string": str, "integer": int, "boolean": bool}
    for key, value in values.items():
        field = fields[key]
        if field["type"] == "array":
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"{key} 的类型错误")
        elif type(value) is not types[field["type"]]:
            raise ValueError(f"{key} 的类型错误")
        if "enum" in field and value not in field["enum"]:
            raise ValueError(f"{key} 的取值无效")
        if "minimum" in field and value < field["minimum"]:
            raise ValueError(f"{key} 小于允许值")


class Tools:
    def __init__(self, store: Store, task_id: str, *, writable: bool = False,
                 agent_edit: str | None = None, read_only: bool = False,
                 exec_allowed: bool = False, network_allowed: bool = True,
                 workspace: Path | None = None, allow_workers: bool = False):
        self.store = store
        self.task_id = task_id
        self.agent_edit = agent_edit
        self.skill_revisions = {}
        self.workspace = (workspace or store.project).resolve()
        self.sandbox = self.workspace if self.workspace != store.project.resolve() else None
        self.allow_workers = allow_workers
        self.processes = set()
        # A Dream task may write memory and resolve its own clues, but never project files or the agent.
        reads = {"read_file", "list_files", "recall", "remember", "clue_done", "compact_context"}
        self.available = {
            s["name"]: s for s in NATIVE
            if (s["name"] != "clue_done" or read_only) and (not read_only or s["name"] in reads)
        }
        if not writable:
            self.available.pop("write_file", None)
            self.available.pop("edit_file", None)
        if not exec_allowed:
            self.available.pop("run_command", None)
        if not network_allowed:
            self.available.pop("web_search", None)
            self.available.pop("web_fetch", None)
        if self.sandbox:
            from ..platform.sandbox import available
            if not available():
                self.available.pop("run_command", None)
        if allow_workers:
            self.available["delegate"] = DELEGATE
            if writable:
                self.available["accept_artifact"] = ACCEPT
        if not agent_edit:
            self.available.pop("revise_agent", None)
        direct = {"read_file", "list_files", "search_files", "recall", "remember", "write_file",
                  "edit_file", "run_command", "web_search", "web_fetch", "revise_agent"}
        if allow_workers:
            direct.add("delegate")
            if writable:
                direct.add("accept_artifact")
        if read_only:
            direct.add("clue_done")
        self.active = {"discover": DISCOVER} | {n: s for n, s in self.available.items() if n in direct}

    def path(self, value: str) -> Path:
        root = self.workspace
        path = (root / value).resolve()
        protected = (self.store.config_path.resolve(), self.store.data.resolve())
        work_root = (self.store.home / "work").resolve()
        if (not path.is_relative_to(root)
                or any(path == item or path.is_relative_to(item) for item in protected)
                or (path.is_relative_to(work_root) and not path.is_relative_to(self.workspace))):
            raise PermissionError("路径超出本任务获准的工作区")
        return path

    def discover(self, kind: str, query: str = "", cold: bool = False) -> list:
        if kind != "tool":
            return self.store.search(query, kind, cold=cold)
        words = normalized(query).split()
        matches = []
        for name, spec in self.available.items():
            label = normalized(name + " " + spec["description"])
            score = sum(word in label for word in words)
            if not words or score:
                matches.append((score, name))
        selected = [name for _, name in sorted(matches, key=lambda row: -row[0])[:6]]
        self.active.update({name: self.available[name] for name in selected})
        return [{"name": name, "description": self.active[name]["description"]} for name in selected]

    def list_files(self, path: str = ".", offset: int = 0) -> dict:
        directory = self.path(path)
        names = sorted(p.name for p in directory.iterdir()
                       if p != self.store.data and p.name not in {".git", ".venv", "__pycache__"})
        end = offset + 100
        return {"entries": names[offset:end], "next_offset": end if len(names) > end else None}

    def read_file(self, path: str, offset: int = 0) -> dict:
        target = self.path(path)
        if not target.is_file():
            raise ValueError("请选择一个普通文件")
        with target.open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576 or b"\0" in raw:
            raise ValueError("内置读取支持 1 MiB 以内的 UTF-8 文本文件")
        text = raw.decode("utf-8")
        end = offset + 12000
        return {"path": str(target.relative_to(self.store.project)), "text": text[offset:end],
                "next_offset": end if len(text) > end else None,
                "sha256": hashlib.sha256(raw).hexdigest()}

    def write_file(self, path: str, text: str, expected: str) -> dict:
        data = text.encode()
        if len(data) > 1_048_576:
            raise ValueError("写入内容超过 1 MiB")
        with self.store.locked():
            dest = self.path(path)
            if dest in (self.store.agent_file, self.store.home / "skills/aiverywhere/SKILL.md",
                        self.store.home / ".project/SKILL.md", skill_template()):
                raise PermissionError("修订 agent 文件需通过单独授权的 revise_agent 或 skill --update")
            if expected == "new":
                if dest.exists():
                    raise ValueError("目标已存在，请先读取现行版本")
            elif self.read_file(path)["sha256"] != expected:
                raise ValueError("文件已变化，请重新读取")
            dest.parent.mkdir(parents=True, exist_ok=True)
            mode = 0o600 if expected == "new" else dest.stat().st_mode & 0o777
            atomic_write(dest, data, create=expected == "new", mode=mode)
        return {"path": str(dest.relative_to(self.workspace)), "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}

    def search_files(self, query: str, path: str = ".", limit: int = 20) -> dict:
        if not isinstance(query, str) or not query.strip() or len(query) > 200:
            raise ValueError("搜索词需要 1–200 个字符")
        maximum = min(max(limit or 20, 1), 50)
        root = self.path(path)
        files = [root] if root.is_file() else []
        if root.is_dir():
            skip = {".git", ".venv", "data", "work", "__pycache__", "node_modules", "dist", "build"}
            for current, dirs, names in os.walk(root):
                dirs[:] = [name for name in dirs if name not in skip and not name.startswith(".")]
                files.extend(Path(current, name) for name in sorted(names))
        found = []
        lowered = query.casefold()
        for source in files:
            if len(found) >= maximum:
                break
            try:
                if (not source.is_file() or source.stat().st_size > 1_048_576
                        or source.resolve() == self.store.config_path.resolve()):
                    continue
                raw = source.read_bytes()
                if b"\0" in raw:
                    continue
                text = raw.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(text.splitlines(), 1):
                if lowered in line.casefold():
                    found.append({"path": str(source.relative_to(self.workspace)),
                                  "line": line_number, "text": line.strip()[:300]})
                    if len(found) >= maximum:
                        break
        return {"query": query, "results": found, "truncated": len(found) >= maximum}

    def edit_file(self, path: str, old: str, new: str, expected: str) -> dict:
        if not old or len(old) > 8000:
            raise ValueError("待替换片段需要 1–8000 个字符")
        if len(new.encode()) > 1_048_576:
            raise ValueError("替换内容超过 1 MiB")
        target = self.path(path)
        if not target.is_file():
            raise ValueError("请选择一个普通文件")
        raw = target.read_bytes()
        if len(raw) > 1_048_576:
            raise ValueError("内置读取支持 1 MiB 以内的 UTF-8 文本文件")
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("文件已变化，请重新读取")
        text = raw.decode("utf-8")
        count = text.count(old)
        if count != 1:
            raise ValueError(f"待替换片段需要唯一匹配，当前匹配 {count} 次")
        data = text.replace(old, new, 1).encode()
        with self.store.locked():
            dest = self.path(path)
            if hashlib.sha256(dest.read_bytes()).hexdigest() != expected:
                raise ValueError("文件已变化，请重新读取")
            mode = dest.stat().st_mode & 0o777
            atomic_write(dest, data, mode=mode)
        return {"path": str(dest.relative_to(self.workspace)), "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}

    def run_command(self, argv: list[str], cwd: str = ".", timeout: int = 60) -> dict:
        if not argv or len(argv) > 64 or any(not item or len(item) > 2000 for item in argv):
            raise ValueError("命令需要 1–64 个非空参数")
        if not isinstance(timeout, int) or not 1 <= timeout <= 300:
            raise ValueError("timeout 需要 1–300 秒")
        directory = self.path(cwd)
        if not directory.is_dir():
            raise ValueError("cwd 需要是一个目录")
        command = list(argv)
        if self.sandbox:
            from ..platform.sandbox import wrap
            command = wrap(self.sandbox, command, deny=(self.store.data,))
        try:
            process = subprocess.Popen(command, cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       start_new_session=True)
        except FileNotFoundError as exc:
            raise ValueError(f"命令不存在：{argv[0]}") from exc
        self.processes.add(process)
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
        finally:
            self.processes.discard(process)
        limit = 20_000
        decoded_out = stdout.decode("utf-8", "replace")
        decoded_err = stderr.decode("utf-8", "replace")
        return {"argv": argv, "exit_code": process.returncode, "timed_out": timed_out,
                "stdout": decoded_out[:limit], "stderr": decoded_err[:limit],
                "truncated": len(decoded_out) > limit or len(decoded_err) > limit}

    def cancel_commands(self) -> None:
        for process in list(self.processes):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    @staticmethod
    def _public_url(url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            raise ValueError("网页地址需要公开的 HTTP(S) URL")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise ValueError("网页域名无法解析") from exc
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise ValueError("网页地址不能指向内网、回环或保留地址")
        return url

    @staticmethod
    def _search_headers() -> dict:
        return {"User-Agent": "aiverywhere/0.1 (+https://github.com/ChanX96/aiverywhere)",
                "Accept": "application/rss+xml,text/html;q=0.9,*/*;q=0.8"}

    @staticmethod
    def _clean_html(value: str) -> str:
        parser = _HTMLText()
        parser.feed(value)
        return parser.text()[:1000]

    def _search_bing(self, query: str) -> list[dict]:
        import httpx
        response = httpx.get("https://www.bing.com/search",
                             params={"q": query, "format": "rss", "count": 5},
                             headers=self._search_headers(), timeout=20, follow_redirects=True)
        if response.status_code == 429:
            raise ValueError("Bing RSS 限流")
        response.raise_for_status()
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise ValueError("Bing RSS 返回了无效 XML") from exc
        results = []
        for item in root.findall(".//item")[:5]:
            title = item.findtext("title") or ""
            url = item.findtext("link") or ""
            description = item.findtext("description") or ""
            if url.startswith(("http://", "https://")):
                results.append({"title": title.strip(), "url": url.strip(),
                                "content": self._clean_html(description)})
        return results

    def _search_duckduckgo(self, query: str) -> list[dict]:
        import httpx
        response = httpx.get("https://html.duckduckgo.com/html/", params={"q": query},
                             headers=self._search_headers(), timeout=20, follow_redirects=True)
        if response.status_code == 429:
            raise ValueError("DuckDuckGo 限流")
        response.raise_for_status()
        parser = _DuckDuckGoResults()
        parser.feed(response.text)
        return parser.results[:5]

    def web_search(self, query: str) -> dict:
        if not query.strip() or len(query) > 500:
            raise ValueError("搜索词需要 1–500 个字符")
        failures = []
        queries = _search_queries(query)
        for name, backend in (("bing-rss", self._search_bing),
                              ("duckduckgo-html", self._search_duckduckgo)):
            results = []
            seen = set()
            for search_query in queries:
                try:
                    found = backend(search_query)
                except Exception as exc:
                    failures.append(f"{name}: {str(exc)[:200] or type(exc).__name__}")
                    continue
                for item in found:
                    if item["url"] not in seen:
                        seen.add(item["url"])
                        results.append(item)
            if results:
                return {"query": query, "results": _rank_results(results, query)[:8], "backend": name}
            failures.append(f"{name}: empty")
        raise ValueError("搜索服务不可用：" + "；".join(failures))

    def web_fetch(self, url: str) -> dict:
        import httpx
        current = url
        client = httpx.Client(follow_redirects=False, timeout=20,
                              headers={"User-Agent": "aiverywhere/0.1 (+https://github.com/ChanX96/aiverywhere)"})
        try:
            for _ in range(4):
                self._public_url(current)
                with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("网页重定向缺少目标")
                        current = urljoin(current, location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if not any(marker in content_type for marker in
                               ("text/", "application/json", "application/xml", "+json", "+xml")):
                        raise ValueError(f"网页不是可读取的文本内容（{content_type or '未知类型'}）")
                    chunks, total = [], 0
                    for chunk in response.iter_bytes():
                        chunks.append(chunk)
                        total += len(chunk)
                        if total > 1_048_576:
                            break
                    raw = b"".join(chunks)
                    encoding = response.encoding or "utf-8"
                    text = raw.decode(encoding, "replace")
                    title = ""
                    if "html" in content_type:
                        parser = _HTMLText()
                        parser.feed(text)
                        text, title = parser.text(), parser.title
                    return {"url": str(response.url), "status": response.status_code,
                            "content_type": content_type, "title": title,
                            "text": text[:20_000], "bytes": total,
                            "truncated": total > 1_048_576 or len(text) > 20_000}
            raise ValueError("网页重定向次数过多")
        except httpx.HTTPStatusError as exc:
            raise ValueError(f"网页返回 HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise ValueError(f"网页请求未完成（{type(exc).__name__}）") from exc
        finally:
            client.close()

    def execute(self, name: str, values: dict):
        if name in {"delegate", "accept_artifact"}:
            raise PermissionError("该工具需要在父任务中执行")
        if name not in self.active:
            raise PermissionError("工具尚未发现或未获授权，请先调用 discover")
        validate_arguments(self.active[name], values)
        if name == "remember":
            return self.store.remember(source=self.task_id, **values)
        if name == "clue_done":
            return self.store.forget_clue(values["id"])
        if name == "compact_context":
            if not 0 < len(values["summary"].strip()) <= 8000:
                raise ValueError("进度摘要应为 1–8000 个字符")
            if len(values.get("concern", "")) > 160:
                raise ValueError("请用 160 字以内说明目标与实际结果的差异")
            return {"compacted": True}
        if name == "recall":
            item = self.store.recall(values["id"])
            if item["kind"] == "skill":
                pinned = self.skill_revisions.setdefault(item["id"], item["revision"])
                if pinned != item["revision"]:
                    raise ValueError("本任务已读取的技能有新修订，请在新任务中采用新版本")
            return item
        if name == "revise_agent":
            return self.store.revise_agent(self.agent_edit, values["text"])
        if name == "share_skill":
            return self.store.share(values["id"], values["revision"], values["evidence"])
        if name == "used_skill":
            return self.store.used_skill(values["id"], values["revision"], values["evidence"])
        dispatch = {
            "discover": self.discover,
            "list_files": self.list_files,
            "read_file": self.read_file,
            "write_file": self.write_file,
            "search_files": self.search_files,
            "edit_file": self.edit_file,
            "run_command": self.run_command,
            "web_search": self.web_search,
            "web_fetch": self.web_fetch,
        }
        if name not in dispatch:
            raise ValueError(f"工具没有本地执行器：{name}")
        return dispatch[name](**values)


class _DuckDuckGoResults(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self._title = None
        self._href = None
        self._text = []
        self._in_snippet = False
        self._snippet = []

    @staticmethod
    def _target(value: str) -> str:
        if value.startswith("//duckduckgo.com/l/"):
            value = "https:" + value
        parts = urlsplit(value)
        if parts.hostname in {"duckduckgo.com", "www.duckduckgo.com"} and parts.path.startswith("/l/"):
            target = parse_qs(parts.query).get("uddg", [""])[0]
            return target
        return value

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        classes = set((fields.get("class") or "").split())
        if tag == "a" and "result__a" in classes:
            self._title, self._href, self._text = "", fields.get("href", ""), []
        elif tag in {"a", "div"} and "result__snippet" in classes:
            self._in_snippet, self._snippet = True, []

    def handle_data(self, data):
        if self._title is not None:
            self._text.append(data)
        if self._in_snippet:
            self._snippet.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._title is not None:
            title = " ".join("".join(self._text).split())
            url = self._target(self._href)
            if title and url.startswith(("http://", "https://")):
                self.results.append({"title": title, "url": url,
                                     "content": " ".join("".join(self._snippet).split())[:1000]})
            self._title = self._href = None
            self._text = []
        if tag in {"a", "div"} and self._in_snippet:
            self._in_snippet = False


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0
        self.title = ""
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if tag in {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "article", "section"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_title:
            self.title += data
        self.parts.append(data)

    def text(self):
        return " ".join(" ".join(self.parts).split())
