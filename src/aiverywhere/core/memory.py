"""File-backed memory-v1 records shared by the CLI, web, and host skill."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .store_errors import RevisionConflict

FIELDS = {"schema_version", "id", "revision", "kind", "title", "text", "source", "updated", "shared"}
KINDS = {"fact", "skill", "clue"}
RECORD_LIMIT = 64 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic(path: Path, data: bytes, *, create: bool = False, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
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


def valid_record(record: dict) -> list[str]:
    errors = []
    if not isinstance(record, dict) or set(record) - FIELDS:
        return ["字段集合不符合 memory-v1"]
    if record.get("schema_version") != 1:
        errors.append("schema_version 必须为 1")
    ident = record.get("id")
    if not isinstance(ident, str) or len(ident) != 32 or any(c not in "0123456789abcdef" for c in ident):
        errors.append("id 需要 32 位小写十六进制")
    revision = record.get("revision")
    if type(revision) is not int or revision < 1:
        errors.append("revision 需要从 1 开始的整数")
    if record.get("kind") not in KINDS:
        errors.append("kind 需要 fact、skill 或 clue")
    for name, limit in (("title", 160), ("text", 8000), ("source", 200)):
        value = record.get(name)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            errors.append(f"{name} 需要非空白且不超过 {limit} 字符")
    updated = record.get("updated")
    if not isinstance(updated, str) or len(updated) != 20 or not updated.endswith("Z"):
        errors.append("updated 需要 ISO-8601 UTC 时间")
    if "shared" in record and type(record["shared"]) is not bool:
        errors.append("shared 需要布尔值")
    return errors


def _updated(value: str) -> float:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0


class MemoryRepository:
    def __init__(self, home: Path, project: Path, *, policy="allow", confirm_shared=False):
        self.home = Path(home).resolve()
        self.project = Path(project).resolve()
        self.policy = policy
        self.confirm_shared = confirm_shared

    @property
    def key(self) -> str:
        manifest = self.home / "instance.json"
        if manifest.is_file():
            try:
                value = json.loads(manifest.read_text())
                if isinstance(value.get("project_key"), str) and value["project_key"]:
                    return value["project_key"]
            except (OSError, ValueError, AttributeError):
                pass
        project_home = self.project / ".aiverywhere"
        try:
            local = self.home == project_home.resolve()
        except OSError:
            local = False
        if local or self.home.is_relative_to(self.project):
            return "default"
        return "p-" + hashlib.sha256(str(self.project).encode()).hexdigest()[:16]

    @property
    def root(self) -> Path:
        return self.home / "data/memory" / self.key

    def _ensure_root(self) -> Path:
        data = self.home / "data"
        data.mkdir(mode=0o700, parents=True, exist_ok=True)
        base = data / "memory"
        if base.is_symlink():
            raise PermissionError("记忆目录不能是符号链接")
        base.mkdir(mode=0o700, exist_ok=True)
        root = base / self.key
        if root.is_symlink():
            raise PermissionError("项目记忆目录不能是符号链接")
        root.mkdir(mode=0o700, exist_ok=True)
        return root

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self.root.glob("*.json")):
            try:
                stat = path.stat()
                digest.update(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}\n".encode())
            except OSError:
                continue
        return digest.hexdigest()

    def _roots(self):
        base = self.home / "data/memory"
        if not base.is_dir():
            return [(self.key, self.root)]
        return [(path.name, path) for path in sorted(base.iterdir()) if path.is_dir()]

    def _visible(self, record: dict, key: str) -> bool:
        if key == self.key:
            return True
        return bool(record.get("shared")) and (
            self.policy == "allow" or self.confirm_shared)

    def _read(self, path: Path) -> dict | None:
        try:
            raw = path.read_bytes()
            if len(raw) > RECORD_LIMIT:
                return None
            record = json.loads(raw)
        except (OSError, ValueError):
            return None
        if valid_record(record):
            return None
        return record

    def items(self) -> list[tuple[str, dict]]:
        root = self.root
        if root.is_symlink():
            raise PermissionError("项目记忆目录不能是符号链接")
        found = []
        for key, root in self._roots():
            if not root.is_dir():
                continue
            for path in sorted(root.glob("*.json")):
                record = self._read(path)
                if record and self._visible(record, key):
                    found.append((key, record))
        return found

    def summary(self, record: dict) -> dict:
        return {name: record.get(name) for name in ("id", "title", "kind", "revision", "updated", "shared")}

    def search(self, query: str, kind: str, *, cold: bool = False, limit: int = 5) -> list:
        if kind not in KINDS:
            raise ValueError("kind 应为 fact、skill 或 clue")
        tokens = [token for token in query.casefold().split() if token]
        cutoff = time.time() - 90 * 86400
        ranked = []
        for _, record in self.items():
            if record["kind"] != kind:
                continue
            stamp = _updated(record["updated"])
            if kind != "clue" and not cold and stamp < cutoff:
                continue
            title = record["title"].casefold()
            body = record["text"].casefold()
            if not all(token in title or token in body for token in tokens):
                continue
            score = sum(2 if token in title else 1 for token in tokens)
            ranked.append((score, stamp, record["id"], self.summary(record)))
        if not ranked and kind == "skill" and self.policy == "ask" and not self.confirm_shared:
            raise PermissionError("本项目没有匹配技能。扩展到共用技能前，请先向用户确认")
        return [row[-1] for row in sorted(ranked, reverse=True)[:limit]]

    def recall(self, ident: str) -> dict:
        for key, record in self.items():
            if record["id"] != ident:
                continue
            if not self._visible(record, key):
                raise PermissionError("使用共用技能前，请先向用户确认")
            return dict(record)
        raise ValueError("当前范围内没有可读取的条目")

    def _path(self, ident: str) -> Path:
        return self.root / f"{ident}.json"

    def _validator(self) -> Path | None:
        candidates = (
            self.home / "skills/aiverywhere/scripts/validate-memory.sh",
            self.home / "data/skills/aiverywhere/scripts/validate-memory.sh",
            Path(__file__).resolve().parents[3] / "skills/aiverywhere/scripts/validate-memory.sh",
        )
        return next((path for path in candidates if path.is_file()), None)

    def _validate(self, record: dict) -> None:
        script = self._validator()
        if script is not None:
            completed = subprocess.run(
                ["sh", str(script)], input=(json.dumps(record, ensure_ascii=False) + "\n").encode(),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            if completed.returncode == 0:
                return
            if completed.returncode == 2:
                raise ValueError("memory-v1 validation failed")
            # Missing jq or an unavailable shell validator falls back to the
            # Python rules; both consume the same schema.
        errors = valid_record(record)
        if errors:
            raise ValueError("; ".join(errors))

    def remember(self, title: str, text: str, kind: str, source: str,
                 *, revision: int | None = None) -> dict:
        title, text = title.strip(), text.strip()
        if kind not in KINDS or not 0 < len(title) <= 160 or not 0 < len(text) <= 8000:
            raise ValueError("条目需要类型 fact、skill 或 clue、简短标题（最多 160 字符）和正文（最多 8000 字符）")
        self._ensure_root()
        existing = next((record for key, record in self.items()
                         if key == self.key and record["kind"] == kind
                         and record["title"].strip().casefold() == title.casefold()), None)
        if existing:
            if existing["text"] == text:
                return self.summary(existing)
            if revision != existing["revision"]:
                raise RevisionConflict("修订冲突，请先读取现行条目再提供 revision")
            record = dict(existing)
            record.update(revision=existing["revision"] + 1, text=text, source=source, updated=_now())
        else:
            if revision is not None:
                raise ValueError("原条目已不存在")
            ident = os.urandom(16).hex()
            record = {"schema_version": 1, "id": ident, "revision": 1, "kind": kind,
                      "title": title, "text": text, "source": source, "updated": _now(),
                      "shared": False}
        self._validate(record)
        target = self._path(record["id"])
        if target.exists() and revision is not None:
            current = self._read(target)
            if not current or current["revision"] != revision:
                raise RevisionConflict("修订冲突，请先读取现行条目")
            _atomic(target, (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode(),
                    mode=target.stat().st_mode & 0o777)
        else:
            _atomic(target, (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode(),
                    create=not target.exists(), mode=0o600)
        return self.summary(record)

    def record(self, ident: str) -> dict:
        record = self._read(self._path(ident))
        if record is None:
            raise ValueError("当前项目没有该条目")
        return record

    def write_record(self, record: dict) -> None:
        self._validate(record)
        target = self._path(record["id"])
        _atomic(target, (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode(),
                mode=target.stat().st_mode & 0o777 if target.exists() else 0o600,
                create=not target.exists())

    def update(self, ident: str, title: str, text: str, kind: str, source: str,
               revision: int) -> dict:
        title, text = title.strip(), text.strip()
        record = self.record(ident)
        if record["revision"] != revision:
            raise RevisionConflict("修订冲突，请先读取现行条目")
        if record["kind"] != kind:
            raise ValueError("条目类型不能修改")
        if not 0 < len(title) <= 160 or not 0 < len(text) <= 8000:
            raise ValueError("标题或正文超出长度限制")
        record.update(title=title, text=text, source=source, revision=revision + 1, updated=_now())
        self.write_record(record)
        return self.summary(record)

    def forget(self, ident: str, revision: int | None = None) -> None:
        for key, record in self.items():
            if record["id"] != ident or key != self.key:
                continue
            if revision is not None and revision != record["revision"]:
                raise RevisionConflict("修订冲突，请核对现行条目")
            self._path(ident).unlink()
            return
        raise ValueError("当前项目没有该条目")

    def changed_revisions(self, used: dict) -> dict:
        changed = {}
        for ident, previous in used.items():
            current = None
            for _, record in self.items():
                if record["id"] == ident:
                    current = record["revision"]
                    break
            if current != previous:
                changed[ident] = current
        return changed

    def migrate(self, state: dict) -> int:
        entries = state.get("memory", {})
        if not isinstance(entries, dict):
            return 0
        migrated = 0
        self._ensure_root()
        for ident, item in entries.items():
            if not isinstance(item, dict) or item.get("project") != str(self.project):
                continue
            target = self._path(ident)
            if target.exists():
                continue
            updated = item.get("updated", 0)
            if isinstance(updated, (int, float)):
                updated = datetime.fromtimestamp(updated, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            record = {
                "schema_version": 1, "id": ident, "revision": int(item.get("revision", 1)),
                "kind": item.get("kind", "fact"), "title": item.get("title", ""),
                "text": item.get("text", ""), "source": item.get("source", "migration"),
                "updated": updated if isinstance(updated, str) else _now(),
                "shared": bool(item.get("shared")),
            }
            try:
                self._validate(record)
                _atomic(target, (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode(),
                        create=True, mode=0o600)
                migrated += 1
            except (OSError, ValueError):
                continue
        state.pop("memory", None)
        return migrated
