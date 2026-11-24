"""Portable migration package for skill, workflow overrides and memory-v1."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import tempfile
import time
from pathlib import Path

from . import workflow
from .memory import valid_record
from .store import Store, atomic_write

FORMAT = "aiverywhere-migration/1"
MANIFEST = "manifest.json"
MAX_FILES = 10_000
MAX_BYTES = 64 * 1024 * 1024


class MigrationError(ValueError):
    pass


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe(relative: str) -> str:
    if not isinstance(relative, str) or relative.startswith("/") or "\\" in relative:
        raise MigrationError("迁移包路径无效")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise MigrationError("迁移包路径越界")
    return relative


def _source_files(store: Store) -> dict[str, tuple[bytes, int, str]]:
    files: dict[str, tuple[bytes, int, str]] = {}
    skill = store.skill_dir
    for relative in ("SKILL.md", "references", "scripts"):
        base = skill / relative
        candidates = [base] if base.is_file() else (
            sorted(base.rglob("*")) if base.is_dir() and not base.is_symlink() else [])
        for path in candidates:
            if not path.is_file() or path.is_symlink():
                continue
            rel = str(path.relative_to(skill))
            if rel == "references/workflow/finish.md" or "__pycache__" in rel:
                continue
            data = path.read_bytes()
            files[f"skill/{rel}"] = (data, path.stat().st_mode & 0o777, "skill")
    overrides = store.home / "overrides" / store.memory.key / "workflow"
    if overrides.is_dir() and not overrides.is_symlink():
        for path in sorted(overrides.glob("*.md")):
            if path.is_file() and not path.is_symlink() and path.stem in workflow.OVERRIDABLE:
                files[f"workflow/{path.name}"] = (path.read_bytes(), 0o600, "workflow")
    memory_root = store.memory.root
    if memory_root.is_dir() and not memory_root.is_symlink():
        for path in sorted(memory_root.glob("*.json")):
            if not path.is_file() or path.is_symlink():
                continue
            record = json.loads(path.read_text())
            if valid_record(record):
                raise MigrationError(f"记忆格式无效：{path.name}")
            files[f"memory/{path.name}"] = (path.read_bytes(), 0o600, "memory")
    total = sum(len(data) for data, _, _ in files.values())
    if len(files) > MAX_FILES or total > MAX_BYTES:
        raise MigrationError("迁移包超过大小限制")
    return files


def _manifest(store: Store, files: dict[str, tuple[bytes, int, str]]) -> dict:
    return {
        "format": FORMAT,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_project_key": store.memory.key,
        "skill_contract": workflow.CONTRACT,
        "files": [{"path": path, "size": len(data), "sha256": _digest(data), "kind": kind}
                  for path, (data, _, kind) in sorted(files.items())],
    }


def export(store: Store, output: Path, *, force: bool = False) -> dict:
    """Create a bounded package of the active skill, overrides, and memory-v1 only."""
    files = _source_files(store)
    manifest = _manifest(store, files)
    output = output.resolve()
    if output.exists() and not force:
        raise MigrationError(f"目标已存在：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with tarfile.open(temporary, "w:gz") as archive:
            payloads = {MANIFEST: (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(),
                        **{path: data for path, (data, _, _) in files.items()}}
            for name, data in payloads.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o600
                info.mtime = int(time.time())
                archive.addfile(info, io.BytesIO(data))
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return {"output": str(output), "files": len(files), "bytes": output.stat().st_size,
            "format": FORMAT, "source_project_key": store.memory.key}


def _members(archive: tarfile.TarFile) -> tuple[dict, dict[str, bytes]]:
    members = archive.getmembers()
    if len(members) > MAX_FILES + 1:
        raise MigrationError("迁移包文件过多")
    found: dict[str, bytes] = {}
    total = 0
    for member in members:
        if not member.isfile() or member.issym() or member.islnk():
            raise MigrationError("迁移包只允许普通文件")
        _safe(member.name)
        data = archive.extractfile(member)
        if data is None:
            raise MigrationError("迁移包文件不可读")
        raw = data.read(MAX_BYTES + 1)
        total += len(raw)
        if total > MAX_BYTES:
            raise MigrationError("迁移包超过大小限制")
        found[member.name] = raw
    if MANIFEST not in found:
        raise MigrationError("迁移包缺少 manifest.json")
    try:
        manifest = json.loads(found.pop(MANIFEST))
    except ValueError as exc:
        raise MigrationError("迁移清单不是有效 JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise MigrationError("不支持的迁移格式")
    rows = manifest.get("files")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise MigrationError("迁移清单文件列表无效")
    expected = {}
    for row in rows:
        path = _safe(row.get("path"))
        size = row.get("size")
        digest = row.get("sha256")
        if not isinstance(size, int) or size < 0 or not isinstance(digest, str):
            raise MigrationError("迁移清单文件摘要无效")
        expected[path] = (size, digest, row.get("kind", ""))
    if set(found) != set(expected):
        raise MigrationError("迁移清单与实际文件不一致")
    for path, raw in found.items():
        size, digest, _ = expected[path]
        if len(raw) != size or _digest(raw) != digest:
            raise MigrationError(f"迁移文件校验失败：{path}")
    return manifest, found


def inspect(package: Path) -> dict:
    """Validate a package without extracting it into the target instance."""
    with tarfile.open(package, "r:gz") as archive:
        manifest, files = _members(archive)
    kinds = {}
    for row in manifest.get("files", []):
        kind = row.get("kind", "file")
        kinds[kind] = kinds.get(kind, 0) + 1
    return {"format": manifest.get("format"), "source_project_key": manifest.get("source_project_key"),
            "skill_contract": manifest.get("skill_contract"), "files": len(files) + 1,
            "kinds": kinds,
            "memory": [row["path"].rsplit("/", 1)[-1] for row in manifest.get("files", [])
                       if row.get("kind") == "memory"][:20]}


def _write_checked(path: Path, data: bytes, mode: int) -> str:
    """Never overwrite a local file or follow a symlink during import."""
    if path.is_symlink():
        return "conflict"
    if path.exists():
        if path.is_file() and path.read_bytes() == data:
            return "skipped"
        return "conflict"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, data, create=True, mode=mode)
    return "imported"


def import_package(store: Store, package: Path) -> dict:
    """Import validated files; identical records are skipped and conflicts are kept local."""
    with tarfile.open(package, "r:gz") as archive:
        manifest, files = _members(archive)
    if manifest.get("skill_contract") != workflow.CONTRACT:
        raise MigrationError("迁移包的 skill 契约版本不兼容")
    result = {"format": manifest.get("format"), "imported": [], "skipped": [], "conflicts": [],
              "memory": {"imported": 0, "skipped": 0, "conflicts": 0}}
    for relative, data in sorted(files.items()):
        parts = Path(relative).parts
        if parts[0] == "memory":
            if len(parts) != 2 or not parts[1].endswith(".json"):
                raise MigrationError("迁移包记忆路径无效")
            try:
                record = json.loads(data)
            except ValueError as exc:
                raise MigrationError("迁移包记忆不是有效 JSON") from exc
            if valid_record(record):
                raise MigrationError("迁移包记忆格式无效")
            status = _write_checked(store.memory.root / parts[1], data, 0o600)
            bucket = {"imported": "imported", "skipped": "skipped", "conflict": "conflicts"}[status]
            result["memory"][bucket] += 1
            if status == "imported":
                result["imported"].append(relative)
            elif status == "skipped":
                result["skipped"].append(relative)
            else:
                result["conflicts"].append(relative)
        elif parts[0] == "workflow":
            if len(parts) != 2 or parts[1] not in {f"{name}.md" for name in workflow.OVERRIDABLE}:
                raise MigrationError("迁移包 workflow 路径无效")
            target = store.home / "overrides" / store.memory.key / "workflow" / parts[1]
            status = _write_checked(target, data, 0o600)
            result[{"imported": "imported", "skipped": "skipped", "conflict": "conflicts"}[status]].append(relative)
        elif parts[0] == "skill":
            if parts[1:] == ["references", "workflow", "finish.md"]:
                # finish is fixed and comes from the target distribution.
                result["skipped"].append(relative)
                continue
            target = store.skill_dir.joinpath(*parts[1:]).resolve()
            root = store.skill_dir.resolve()
            if not target.is_relative_to(root):
                raise MigrationError("迁移包 skill 路径越界")
            status = _write_checked(target, data, 0o755 if parts[1] == "scripts" else 0o644)
            result[{"imported": "imported", "skipped": "skipped", "conflict": "conflicts"}[status]].append(relative)
        else:
            raise MigrationError("迁移包含未知分区")
    result["verified"] = bool(store.load_agent() and store.memory.items() is not None)
    return result
