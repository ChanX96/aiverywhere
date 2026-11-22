"""Depth-one delegated workers with private workspaces and artifact hand-off."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path

from .agent import Task
from .store import atomic_write

IGNORE_NAMES = (".git", ".venv", "data", "node_modules", "dist", "build", "__pycache__",
                ".agents", ".aiverywhere-sandbox.sb")
IGNORE = shutil.ignore_patterns(*IGNORE_NAMES)
MAX_ARTIFACT = 8 * 1024 * 1024
MAX_ARTIFACTS = 40


def _snapshot(root: Path) -> dict[str, str]:
    result = {}
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            try:
                result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
    return result


def _workspace(parent: Task, index: int) -> tuple[Path, dict[str, str]]:
    target = parent.store.home / "work" / parent.id / f"worker-{index}"
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    ignore = IGNORE
    if parent.store.project.resolve() == parent.store.home.resolve():
        ignore = shutil.ignore_patterns("config.json", *IGNORE_NAMES)
    shutil.copytree(parent.store.project, target, ignore=ignore, symlinks=True)
    return target, _snapshot(target)


def _artifacts(parent: Task, worker: Task, label: str, workspace: Path,
               baseline: dict[str, str]) -> list[dict]:
    root = parent.store.data / "artifacts" / parent.id / label
    found = []
    for path in sorted(workspace.rglob("*")):
        if len(found) >= MAX_ARTIFACTS:
            break
        if not path.is_file() or path.is_symlink() or path.name == ".aiverywhere-sandbox.sb":
            continue
        relative = str(path.relative_to(workspace))
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if len(data) > MAX_ARTIFACT:
            continue
        digest = hashlib.sha256(data).hexdigest()
        if baseline.get(relative) == digest:
            continue
        ident = f"{label}-{len(found) + 1}"
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(destination, data, mode=0o600)
        preview = ""
        if b"\0" not in data and len(data) <= 262_144:
            try:
                preview = data.decode("utf-8")[:500]
            except UnicodeDecodeError:
                preview = ""
        record = {"id": ident, "path": relative, "size": len(data), "sha256": digest,
                  "worker": label, "source": str(destination), "preview": preview}
        parent.artifacts[ident] = record
        found.append({key: record[key] for key in ("id", "path", "size", "sha256", "worker", "preview")})
    return found


async def delegate(parent: Task, tasks: list[str], provider) -> dict:
    if not parent.allow_workers:
        raise PermissionError("本任务未获准委派 worker")
    if not 1 <= len(tasks) <= min(parent.worker_limit, 2):
        raise ValueError("delegate 需要 1–2 个子任务")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 4000 for item in tasks):
        raise ValueError("每个子任务需要 1–4000 个字符")

    async def run_one(index: int, description: str) -> dict:
        ident = f"w{index}"
        workspace = None
        try:
            workspace, baseline = await asyncio.to_thread(_workspace, parent, index)
            worker = Task(parent.store, writable=True, exec_allowed=parent.exec_allowed,
                          network_allowed=parent.network_allowed,
                          workspace=workspace, entry="worker", allow_workers=False)
            if parent.worker_callback:
                worker.activity_callback = lambda action: parent.worker_callback({
                    "id": ident, "status": "running", "action": action, "description": description})
            handle = asyncio.current_task()
            parent.worker_tasks[ident] = handle
            if parent.worker_callback:
                parent.worker_callback({"id": ident, "status": "started", "description": description})
            prompt = (f"子任务：{description}\n主任务目标：{parent.goal or ''}\n"
                      "在私有工作区完成，交回简洁结果、证据和产物说明。不要修改实例配置。")
            await worker.run(prompt, provider, max_turns=max(2, min(parent.max_turns, 8)),
                             timeout=parent.timeout)
            artifacts = await asyncio.to_thread(_artifacts, parent, worker, ident, workspace, baseline)
            result = {"id": ident, "status": worker.status, "answer": worker.answer[:8000],
                      "error": worker.error[:2000], "receipts": worker.result()["receipts"],
                      "artifacts": artifacts}
            if parent.worker_callback:
                parent.worker_callback({"id": ident, "status": worker.status, "description": description})
            return result
        except asyncio.CancelledError:
            worker.status = "cancelled"
            if parent.worker_callback:
                parent.worker_callback({"id": ident, "status": "cancelled", "description": description})
            return {"id": ident, "status": "cancelled", "answer": "", "error": "worker 已取消",
                    "artifacts": []}
        except Exception as exc:
            if parent.worker_callback:
                parent.worker_callback({"id": ident, "status": "failed", "description": description})
            return {"id": ident, "status": "failed", "answer": "", "error": str(exc), "artifacts": []}
        finally:
            parent.worker_tasks.pop(ident, None)

    results = await asyncio.gather(*(run_one(index + 1, item) for index, item in enumerate(tasks)))
    return {"workers": results, "artifacts": [item for result in results for item in result["artifacts"]]}


def accept_artifact(parent: Task, artifact_id: str, path: str, expected: str) -> dict:
    if not parent.writable:
        raise PermissionError("写入项目需要 --allow-write")
    record = parent.artifacts.get(artifact_id)
    if not record:
        raise ValueError("没有这个产物；先调用 delegate 并核对产物 ID")
    source = Path(record["source"])
    if not source.is_file():
        raise ValueError("产物文件已不存在")
    root = parent.store.project.resolve()
    target = (root / path).resolve()
    protected = (parent.store.config_path.resolve(), parent.store.data.resolve(),
                 (parent.store.home / "work").resolve())
    if (not target.is_relative_to(root)
            or any(target == item or target.is_relative_to(item) for item in protected)):
        raise PermissionError("目标超出项目范围")
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise ValueError("产物哈希已变化")
    if expected == "new":
        if target.exists():
            raise ValueError("目标已存在，请传入目标现行 sha256")
        mode = 0o600
    else:
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError("目标已变化，请重新读取")
        mode = target.stat().st_mode & 0o777
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, data, create=expected == "new", mode=mode)
    return {"artifact_id": artifact_id, "path": str(target.relative_to(root)),
            "bytes": len(data), "sha256": record["sha256"]}
