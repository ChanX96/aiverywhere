"""Private, single-user instance state. All writers use the same POSIX lock."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import unicodedata
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path

from .memory import MemoryRepository
from .store_errors import RevisionConflict


RUNTIME_KEYS = ("plans", "jobs", "runs", "notices")
CONFIG_SECTIONS = ("model", "defaults", "mcpServers", "wechat", "session", "channels")
RUNTIME_DEFAULTS = {"max_turns": 12, "timeout": 180, "port": 8765}
SESSION_DEFAULTS = {"max_context_tokens": 64000, "compact_at": 0.8,
                    "keep_recent_turns": 6, "summary_max_chars": 4000}


def runtime_fields(state: dict) -> dict:
    return {key: state.get(key, {}) for key in RUNTIME_KEYS} | {"version": state["version"]}


def user_home() -> Path:
    """The canonical user-level install root created by install.sh."""
    return Path("~/.aiverywhere").expanduser()


def _linked_home(project: Path) -> Path | None:
    """A project link points at <home>/data/SKILL.md; use it to find a custom home."""
    link = project / ".agents/skills/aiverywhere/SKILL.md"
    if not link.is_symlink():
        return None
    target = link.resolve()
    if target.name == "aiverywhere" and (target / "SKILL.md").is_file():
        for home in (target.parent.parent, target.parent.parent.parent):
            if (home / "instance.json").is_file() or (home / "config.json").is_file():
                return home
    home = target.parent.parent
    if target.name == "SKILL.md" and target.parent.name == "data" and (
            (home / "config.json").is_file() or (home / "data/config.json").is_file()):
        return home
    return None


def instance_root(*, required: bool = False) -> Path:
    """Find the installation project independently of the task's working directory."""
    if override := os.getenv("AIVERYWHERE_HOME"):
        return Path(override).expanduser().resolve()
    cwd = Path.cwd().resolve()
    # A project-local skill instance is the default shell-first binding.
    for candidate in (cwd, *cwd.parents):
        local = candidate / ".aiverywhere"
        if (local / "instance.json").is_file():
            return local
    source = Path(__file__).resolve().parent
    if source.parents[1].name == "src" and (source.parents[2] / "skills/aiverywhere/SKILL.md").is_file():
        return source.parents[2]
    # A wheel in a project-local venv can still find its project from another cwd.
    candidates = [*Path(sys.prefix).resolve().parents] if sys.prefix != sys.base_prefix else []
    for candidate in (*candidates, cwd, *cwd.parents):
        if any((candidate / name).is_file() for name in
               ("data/SKILL.md", "skills/aiverywhere/SKILL.md", ".project/SKILL.md")):
            return candidate
        if home := _linked_home(candidate):
            return home
    # A user-level install is reachable from any working directory.
    installed = user_home()
    if any((installed / name).is_file() for name in ("config.json", "data/SKILL.md")):
        return installed.resolve()
    if required:
        raise ValueError("请先运行 aiverywhere init，或使用 install.sh 安装；也可用 --home 指定安装根")
    return cwd


def checked_defaults(raw: dict) -> dict:
    """Validate an optional defaults partition and merge it over the built-ins."""
    if not isinstance(raw, dict) or raw.keys() - RUNTIME_DEFAULTS.keys():
        raise ValueError("config.json 的 defaults 只支持 max_turns、timeout、port")
    merged = dict(RUNTIME_DEFAULTS)
    for key, value in raw.items():
        if type(value) is not int:
            raise ValueError(f"defaults.{key} 需要整数")
        if key == "port":
            if not 0 <= value <= 65535:
                raise ValueError("defaults.port 须在 0–65535 之间")
        elif value <= 0:
            raise ValueError(f"defaults.{key} 需要正整数")
        merged[key] = value
    return merged


def checked_session(raw: dict) -> dict:
    """Validate the optional session budget partition."""
    if not isinstance(raw, dict) or raw.keys() - SESSION_DEFAULTS.keys():
        raise ValueError("config.json 的 session 只支持 max_context_tokens、compact_at、keep_recent_turns、summary_max_chars")
    merged = dict(SESSION_DEFAULTS)
    for key, value in raw.items():
        if key == "compact_at":
            if type(value) not in (int, float) or not 0 < float(value) < 1:
                raise ValueError("session.compact_at 须在 0 和 1 之间")
        elif type(value) is not int:
            raise ValueError(f"session.{key} 需要整数")
        if key == "max_context_tokens" and value < 1000:
            raise ValueError("session.max_context_tokens 至少为 1000")
        if key == "keep_recent_turns" and value < 1:
            raise ValueError("session.keep_recent_turns 至少为 1")
        if key == "summary_max_chars" and not 200 <= value <= 16000:
            raise ValueError("session.summary_max_chars 须在 200–16000 之间")
        merged[key] = value
    return merged


def project_file(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.resolve().is_relative_to(root) or path.is_symlink():
        raise PermissionError(f"实例文件须保存在项目内：{relative}")
    return path


def file_version(path: Path):
    """Notice atomic replacement, in-place edits, creation and deletion using stat."""
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    return info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def skill_template():
    packaged = files("aiverywhere").joinpath("skill/SKILL.md")
    if packaged.is_file():
        return packaged
    installed = files("aiverywhere").joinpath("SKILL.md")
    if installed.is_file():
        return installed
    return Path(__file__).resolve().parents[3] / "skills/aiverywhere/SKILL.md"


def skill_text(home: Path | None = None) -> str:
    root = home.resolve() if home is not None else instance_root()
    for relative in ("data/SKILL.md", ".project/SKILL.md", "skills/aiverywhere/SKILL.md"):
        path = project_file(root, relative)
        if path.is_file():
            return path.read_bytes().decode("utf-8")
    return skill_template().read_bytes().decode("utf-8")


def skill_revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().strip()


def worker_alive(record: dict, now: float) -> bool:
    if not record.get("pid") or record.get("expires", 0) <= now:
        return False
    try:
        os.kill(record["pid"], 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def atomic_write(path: Path, data: bytes, *, create: bool = False, mode: int = 0o600) -> None:
    """Publish a complete file on the same filesystem, including after a restart."""
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            os.fchmod(stream.fileno(), mode)
            stream.flush()
            os.fsync(stream.fileno())
            if create:
                os.link(temporary, path)
            else:
                os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)


class Store:
    def __init__(self, home: Path, project: Path, *, confirm_shared: bool = False):
        self.home = home.resolve()
        self.project = project.resolve(strict=True)
        if not self.project.is_dir():
            raise ValueError("项目路径必须是目录")
        self.confirm_shared = confirm_shared

    @property
    def data(self) -> Path:
        return project_file(self.home, "data")

    @property
    def config_path(self) -> Path:
        return project_file(self.home, "config.json")

    @property
    def memory(self) -> MemoryRepository:
        policy = "allow"
        try:
            policy = self.snapshot().get("shared_policy", "allow")
        except (OSError, ValueError):
            pass
        return MemoryRepository(self.home, self.project, policy=policy,
                                confirm_shared=self.confirm_shared)

    def local(self, name: str) -> Path:
        return project_file(self.data, name)

    @property
    def path(self) -> Path:
        return self.local("state.json")

    @property
    def skill_dir(self) -> Path:
        for candidate in (self.home / "skills/aiverywhere", self.home / "data/skills/aiverywhere"):
            if (candidate / "SKILL.md").is_file():
                return candidate
        return self.data

    @property
    def agent_file(self) -> Path:
        return self.skill_dir / "SKILL.md"

    def configuration(self) -> dict:
        """A unified file is authoritative; init imports old configurations once."""
        path = self.config_path
        legacy = self.local("config.json")
        if path.exists() and legacy.exists() and path.read_bytes() != legacy.read_bytes():
            raise ValueError("config.json 与旧 data/config.json 内容不同，请保留一份后重试")
        if path.exists():
            cfg = json.loads(path.read_bytes())
        elif legacy.exists():
            cfg = json.loads(legacy.read_bytes())
        else:
            cfg = {}
            for name, key in (("model", "model"), ("mcp", "mcpServers"), ("wechat", "wechat")):
                legacy = self.local(name + ".json")
                if legacy.is_file():
                    value = json.loads(legacy.read_bytes())
                    if name == "mcp":
                        if not isinstance(value, dict) or not isinstance(value.get(key), dict):
                            raise ValueError("旧版 data/mcp.json 需要 mcpServers 对象")
                        value = value[key]
                    cfg[key] = value
        if (not isinstance(cfg, dict) or cfg.keys() - set(CONFIG_SECTIONS)
                or not all(isinstance(value, dict) for value in cfg.values())):
            raise ValueError("config.json 的可选分区为 model、defaults、mcpServers、wechat、session、channels，每个分区须为对象")
        checked_session(cfg.get("session", {}))
        return cfg

    def defaults(self) -> dict:
        """Built-in run budgets, overridden by the optional defaults section."""
        return checked_defaults(self.configuration().get("defaults", {}))

    def session_settings(self) -> dict:
        return checked_session(self.configuration().get("session", {}))

    def _seed_packaged_skill(self) -> None:
        """Install the complete bundled skill for wheel-only CLI installs."""
        target = self.home / "skills/aiverywhere"
        if (target / "SKILL.md").is_file() or (self.home / "data/SKILL.md").is_file():
            return
        try:
            source = files("aiverywhere").joinpath("skill")
            if not source.joinpath("SKILL.md").is_file() or target.is_symlink():
                return
            from importlib.resources import as_file
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with as_file(source) as path:
                shutil.copytree(path, target, dirs_exist_ok=False)
            for script in (target / "scripts").glob("*.sh") if (target / "scripts").is_dir() else ():
                script.chmod(0o755)
        except (OSError, ValueError, AttributeError):
            # A host-only install or a source checkout may have no packaged copy;
            # the regular skill link/fallback still works.
            return

    def initialize(self) -> dict:
        self._seed_packaged_skill()
        info = self.skill_info()
        with self.locked():
            if self.home.name == ".aiverywhere" and self.home.parent == self.project:
                manifest = self.home / "instance.json"
                if not manifest.exists():
                    atomic_write(manifest, (json.dumps({
                        "schema_version": 1, "project_key": "default",
                        "project_root": str(self.project), "instance_root": str(self.home),
                    }, ensure_ascii=False, indent=2) + "\n").encode(),
                                 create=True, mode=0o600)
            cfg = self.configuration()
            path = self.config_path
            legacy = self.local("config.json")
            if not path.exists():
                complete = {key: cfg.get(key, {}) for key in CONFIG_SECTIONS}
                atomic_write(path, (json.dumps(complete, ensure_ascii=False, indent=2) + "\n").encode(),
                             create=True, mode=0o600)
            if legacy.exists():
                legacy.unlink()
        if self.path.exists():
            with self.edit() as state:
                if state.get("memory"):
                    self.memory.migrate(state)
        return {"home": str(self.home), "config": str(path), "agent": info}

    def snapshot(self, *, runtime_only: bool = False) -> dict:
        try:
            with self.path.open("rb") as stream:
                first = stream.readline() if runtime_only else b""
                # New snapshots are ordinary v1 JSON. The first line holds every
                # scheduler field. Older or reformatted files use the full reader.
                if first.startswith(b'{"plans":') and first.endswith(b',"version":1,\n'):
                    try:
                        header = json.loads(first[:-2] + b"}")
                    except json.JSONDecodeError:
                        pass
                    else:
                        if header.keys() in ({*RUNTIME_KEYS, "version"},
                                             {*RUNTIME_KEYS, "dream_pending", "version"}):
                            return header
                state = json.loads(first + stream.read())
        except FileNotFoundError:
            return {} if runtime_only else {"version": 1, "shared_policy": "allow"}
        if not isinstance(state, dict) or state.get("version") != 1:
            raise ValueError("实例状态版本不受支持")
        return runtime_fields(state) if runtime_only else state

    @contextmanager
    def locked(self):
        self.data.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.local(".lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    @contextmanager
    def edit(self):
        with self.locked():
            state = self.snapshot()
            yield state
            header = runtime_fields(state)
            body = {key: value for key, value in state.items() if key not in header}
            first = json.dumps(header, ensure_ascii=False, separators=(",", ":"))[:-1]
            rest = json.dumps(body, ensure_ascii=False, separators=(",", ":"))[1:]
            atomic_write(self.path, (first + ",\n" + rest).encode())

    def agent_files(self) -> list[dict]:
        """List editable files in the live skill bundle (SKILL.md + references/scripts)."""
        self.load_agent()
        root = self.skill_dir
        files = []
        candidates = [root / "SKILL.md"]
        for folder in ("references", "scripts"):
            base = root / folder
            if base.is_dir() and not base.is_symlink():
                candidates.extend(sorted(path for path in base.iterdir()
                                         if path.is_file() and not path.is_symlink()))
        for path in candidates:
            if not path.is_file() or path.is_symlink():
                continue
            try:
                raw = path.read_bytes()
                relative = str(path.relative_to(root))
            except OSError:
                continue
            files.append({"path": relative, "size": len(raw),
                          "sha256": hashlib.sha256(raw).hexdigest(),
                          "revision": (skill_revision(raw.decode("utf-8", "replace"))
                                       if relative == "SKILL.md" else hashlib.sha256(raw).hexdigest())})
        return files

    def _agent_path(self, relative: str) -> Path:
        if (not isinstance(relative, str) or relative.startswith("/") or "\\" in relative
                or any(part in {"", ".", ".."} for part in relative.split("/"))):
            raise ValueError("agent 文件路径无效")
        root = self.skill_dir.resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or path == root or path.is_symlink():
            raise ValueError("agent 文件路径超出 bundle")
        if relative != "SKILL.md" and not (
                relative.startswith("references/") and path.suffix in {".md", ".json"}
                or relative.startswith("scripts/") and path.suffix == ".sh"):
            raise ValueError("只允许编辑 SKILL.md、references/*.md/json 和 scripts/*.sh")
        return path

    def read_agent_file(self, relative: str) -> dict:
        path = self._agent_path(relative)
        if relative == "SKILL.md":
            text = self.load_agent()
            return {"path": relative, "text": text, "revision": skill_revision(text)}
        if not path.is_file():
            raise ValueError("agent 文件不存在")
        raw = path.read_bytes()
        if len(raw) > 131072 or b"\0" in raw:
            raise ValueError("agent 文件需要是 128 KiB 以内的 UTF-8 文本")
        text = raw.decode("utf-8")
        return {"path": relative, "text": text, "revision": hashlib.sha256(raw).hexdigest()}

    def write_agent_file(self, relative: str, text: str, expected: str) -> dict:
        if not isinstance(text, str) or len(text.encode()) > 131072:
            raise ValueError("agent 文件需要是 128 KiB 以内的 UTF-8 文本")
        if relative == "SKILL.md":
            return self.revise_agent(expected, text)
        path = self._agent_path(relative)
        with self.locked():
            if expected == "new":
                if path.exists():
                    raise ValueError("agent 文件已存在")
                mode = 0o755 if relative.startswith("scripts/") else 0o644
                path.parent.mkdir(parents=True, exist_ok=True)
            else:
                if not path.is_file():
                    raise ValueError("agent 文件不存在")
                if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError("agent 文件已变化，请重新读取")
                mode = path.stat().st_mode & 0o777
            atomic_write(path, text.encode(), create=expected == "new", mode=mode)
        return {"path": relative, "revision": hashlib.sha256(text.encode()).hexdigest()}

    def load_agent(self, *, require_path: bool = False) -> str:
        """A writable instance gives the CLI and a native host the same live file."""
        if not self.agent_file.is_file():
            try:
                with self.locked():
                    if not self.agent_file.is_file():
                        self._write_skill(skill_text(self.home), create=True)
            except OSError as exc:
                if require_path or exc.errno not in {errno.EROFS, errno.EACCES, errno.EPERM}:
                    raise
        return skill_text(self.home)

    def skill_info(self) -> dict:
        text = self.load_agent(require_path=True)
        return {"path": str(self.agent_file), "revision": skill_revision(text)}

    def _write_skill(self, text: str, *, create: bool) -> None:
        if not self.agent_file.resolve().is_relative_to(self.home):
            raise PermissionError("活动 agent 文件需位于可写实例内")
        self.agent_file.parent.mkdir(parents=True, exist_ok=True)
        mode = 0o600 if create else self.agent_file.stat().st_mode & 0o777
        atomic_write(self.agent_file, text.encode(), create=create, mode=mode)

    def revise_agent(self, expected: str, text: str) -> dict:
        with self.locked():
            current = skill_text(self.home)
            if skill_revision(current) != expected:
                raise RevisionConflict("agent 文件修订冲突，请核对现行版本")
            header, delimiter, body = text.replace("\r\n", "\n").partition("\n---\n")
            previous = current.replace("\r\n", "\n").partition("\n---\n")[0]
            if (not delimiter or header != previous or not body.strip()
                    or len(text.encode()) > 65536):
                raise ValueError("请保留宿主注册用的文件头，提供非空正文及不超过 64 KiB 的完整 SKILL.md")
            self._write_skill(text, create=not self.agent_file.exists())
        return {"path": str(self.agent_file), "revision": skill_revision(text)}

    def delete_agent(self, expected: str) -> None:
        """Only the local edition is removable. The distributed seed stays available."""
        with self.locked():
            if not self.agent_file.is_file() or skill_revision(skill_text(self.home)) != expected:
                raise RevisionConflict("agent 文件修订冲突，请重新加载")
            self.agent_file.unlink()

    def link_agent(self, directory: Path | None = None) -> dict:
        """Expose the live agent through the host-neutral Agent Skills layout."""
        self.skill_info()
        base = Path(directory) if directory is not None else Path(".agents/skills/aiverywhere")
        if not base.is_absolute():
            base = self.project / base
        base = base.expanduser()
        source = self.agent_file.resolve()
        if self.skill_dir != self.data:
            if base.is_symlink():
                target = base.resolve()
                if target == self.skill_dir.resolve():
                    return {"path": str(base), "target": str(self.skill_dir), "created": False}
                if target.name == "SKILL.md" and target.parent.name == "data":
                    base.unlink()
                    os.symlink(self.skill_dir, base)
                    return {"path": str(base), "target": str(self.skill_dir), "created": True}
            if base.exists():
                raise ValueError(f"技能链接已存在且指向其他位置，未覆盖：{base}")
            base.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(self.skill_dir, base)
            return {"path": str(base), "target": str(self.skill_dir), "created": True}
        target = base / "SKILL.md"
        base.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            if target.resolve() == source:
                return {"path": str(target), "target": str(source), "created": False}
            if not target.exists():
                target.unlink()
                os.symlink(source, target)
                return {"path": str(target), "target": str(source), "created": True}
        if target.exists():
            raise ValueError(f"技能链接已存在且指向其他位置，未覆盖：{target}")
        os.symlink(source, target)
        return {"path": str(target), "target": str(source), "created": True}

    def memory_items(self) -> list[dict]:
        return [self.memory.summary(record) for _, record in self.memory.items()]

    def changed_revisions(self, used: dict) -> dict:
        return self.memory.changed_revisions(used)

    def search(self, query: str, kind: str, *, cold: bool = False, limit: int = 5) -> list:
        return self.memory.search(query, kind, cold=cold, limit=limit)

    def recall(self, item_id: str) -> dict:
        return self.memory.recall(item_id)

    def remember(self, title: str, text: str, kind: str, source: str,
                 *, revision: int | None = None) -> dict:
        with self.locked():
            return self.memory.remember(title, text, kind, source, revision=revision)

    def update(self, item_id: str, title: str, text: str, kind: str, source: str,
               revision: int) -> dict:
        with self.locked():
            return self.memory.update(item_id, title, text, kind, source, revision)

    def save_entry(self, state: dict, title: str, text: str, kind: str, source: str,
                   *, revision: int | None = None, item_id: str | None = None) -> dict:
        if item_id is None:
            return self.remember(title, text, kind, source, revision=revision)
        if revision is None:
            raise ValueError("更新条目需要现行 revision")
        return self.update(item_id, title, text, kind, source, revision)

    def share(self, item_id: str, revision: int, evidence: str) -> dict:
        if not evidence.strip() or len(evidence) > 1000:
            raise ValueError("共享技能需要可核对的验证依据（最多 1000 字符）")
        with self.locked():
            record = self.memory.record(item_id)
            if record["revision"] != revision or record["kind"] != "skill":
                raise RevisionConflict("修订冲突，请先核对技能内容")
            record["shared"] = True
            self.memory.write_record(record)
            return self.memory.summary(record)

    def used_skill(self, item_id: str, revision: int, evidence: str) -> dict:
        if not evidence.strip() or len(evidence) > 1000:
            raise ValueError("请提供本次成功复用的验证依据（最多 1000 字符）")
        record = self.memory.record(item_id)
        if record["revision"] != revision or record["kind"] != "skill":
            raise ValueError("技能已更新，请核对本次采用的版本")
        return self.memory.summary(record)

    def forget(self, item_id: str, revision: int | None = None) -> None:
        with self.locked():
            self.memory.forget(item_id, revision)

    def forget_clue(self, item_id: str) -> dict:
        with self.locked():
            record = self.memory.record(item_id)
            if record["kind"] != "clue":
                raise ValueError("当前项目没有该线索")
            self.memory.forget(item_id)
        return {"deleted": item_id}

    def _runs_dir(self) -> Path:
        path = self.data / "runs"
        if path.is_symlink():
            raise PermissionError("运行记录目录不能是符号链接")
        path.mkdir(mode=0o700, exist_ok=True)
        if not path.resolve().is_relative_to(self.home.resolve()):
            raise PermissionError("运行记录目录必须位于实例内")
        return path

    def _run_path(self, task_id: str) -> Path:
        if not isinstance(task_id, str) or not task_id or len(task_id) > 200:
            raise ValueError("任务标识无效")
        return self._runs_dir() / (hashlib.sha256(task_id.encode()).hexdigest() + ".json")

    def run_detail(self, run_id: str) -> dict:
        path = self._run_path(run_id)
        if not path.is_file() or path.is_symlink():
            raise ValueError("没有该任务的详细运行记录")
        try:
            data = json.loads(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise ValueError("详细运行记录损坏") from exc
        if (not isinstance(data, dict) or data.get("run_id") != run_id
                or data.get("project") != str(self.project)):
            raise ValueError("详细运行记录不属于当前任务")
        return data

    def audit(self, task_id: str, status: str, calls: int, *, run_id: str | None = None,
              detail: dict | None = None) -> None:
        run_id = run_id or task_id
        event = {"task_id": task_id, "run_id": run_id, "project": str(self.project),
                 "time": time.time(), "status": status, "tool_calls": calls}
        with self.locked():
            with self.local("events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            if detail is not None:
                payload = {"task_id": task_id, "run_id": run_id, "project": str(self.project),
                           "time": event["time"], "status": status, "tool_calls": calls,
                           **detail}
                atomic_write(self._run_path(run_id),
                             (json.dumps(payload, ensure_ascii=False) + "\n").encode(),
                             mode=0o600)
