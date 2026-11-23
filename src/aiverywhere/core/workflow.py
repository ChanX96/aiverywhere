"""On-demand workflow modules and project-level overrides."""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

from .store import Store

MODULES = ("plan", "recall", "execute", "extract", "finish")
OVERRIDABLE = {"plan", "recall", "execute", "extract"}
CONTRACT = 1
_CONTRACT = re.compile(r"(?:契约版本|contract\s+version)\s*[:：]?\s*(\d+)", re.IGNORECASE)


class WorkflowError(ValueError):
    """A workflow module or override cannot be used safely."""


def default_dir(store: Store) -> Path:
    local = store.skill_dir / "references" / "workflow"
    if local.is_dir():
        return local
    packaged = files("aiverywhere").joinpath("skill/references/workflow")
    if packaged.is_dir():
        return Path(str(packaged))
    return Path(__file__).resolve().parents[3] / "skills/aiverywhere/references/workflow"


def override_dir(store: Store) -> Path:
    return store.home / "overrides" / store.memory.key / "workflow"


def _contract(text: str) -> int:
    match = _CONTRACT.search(text)
    return int(match[1]) if match else 0


def _override_path(store: Store, name: str) -> Path:
    root = override_dir(store)
    path = root / f"{name}.md"
    if path.is_file():
        try:
            if not path.resolve().is_relative_to(root.resolve()):
                raise WorkflowError(f"workflow 覆盖文件越界：{path.name}")
        except OSError as exc:
            raise WorkflowError(f"workflow 覆盖文件不可读取：{path.name}") from exc
    return path


def _read(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise WorkflowError(f"workflow 模块不可读取：{path.name}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkflowError(f"workflow 模块不可读取：{path.name}") from exc
    if len(text) > 64 * 1024:
        raise WorkflowError(f"workflow 模块超过 64 KiB：{path.name}")
    return text


def module_info(store: Store, name: str) -> dict:
    if name not in MODULES:
        raise WorkflowError(f"未知 workflow 模块：{name}")
    default = default_dir(store) / f"{name}.md"
    text = _read(default)
    version = _contract(text)
    row = {"name": name, "source": "default", "path": str(default),
           "contract": version, "compatible": version == CONTRACT,
           "override": None, "ignored_override": None}
    override = _override_path(store, name)
    if name not in OVERRIDABLE:
        if override.is_file():
            row["ignored_override"] = str(override)
        return row
    if override.is_file():
        override_text = _read(override)
        override_version = _contract(override_text)
        row.update(source="override", path=str(override), contract=override_version,
                   compatible=override_version == CONTRACT, override=str(override))
        if override_version != CONTRACT:
            row["error"] = f"{name} 覆盖模块契约版本 {override_version or '缺失'} 不兼容（需要 {CONTRACT}）"
    return row


def list_modules(store: Store) -> list[dict]:
    return [module_info(store, name) for name in MODULES]


def load_module(store: Store, name: str) -> dict:
    row = module_info(store, name)
    if row.get("error"):
        raise WorkflowError(row["error"])
    if not row["compatible"]:
        raise WorkflowError(f"{name} workflow 模块契约版本不兼容")
    path = Path(row["path"])
    return {"name": name, "source": row["source"], "path": str(path),
            "contract": row["contract"], "text": _read(path),
            "ignored_override": row.get("ignored_override")}


def paths(store: Store) -> dict:
    return {"default": str(default_dir(store)), "overrides": str(override_dir(store)),
            "project_key": store.memory.key, "contract": CONTRACT}
