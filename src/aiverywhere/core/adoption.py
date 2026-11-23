"""Small, reversible host auto-adoption blocks in project rule files."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from .store import Store, atomic_write

BEGIN = "<!-- aiverywhere:begin -->"
END = "<!-- aiverywhere:end -->"
BLOCK = """<!-- aiverywhere:begin -->
本项目采用 AIVERYWHERE 工作约定，使用当前宿主自己的模型、工具和权限。
首次处理项目记忆、历史约定、多步骤执行或迁移时，从项目根目录读取
`.agents/skills/aiverywhere/SKILL.md`，按任务需要加载对应模块。
明确要求记住或纠正时，保存后回读确认。“仅本次”只用于当前任务。
普通问答直接回答。用户要求不要记时，跳过持久化。
<!-- aiverywhere:end -->"""
ALLOWED = {"AGENTS.md", "CLAUDE.md", ".cursor/rules/aiverywhere.mdc"}


class AdoptionError(ValueError):
    pass


def settings_path(store: Store) -> Path:
    return store.data / "project-settings" / f"{store.memory.key}.json"


def _state(store: Store) -> dict:
    path = settings_path(store)
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _save(store: Store, **changes) -> dict:
    path = settings_path(store)
    value = _state(store)
    value.update(changes)
    value["schema_version"] = 1
    value["project_key"] = store.memory.key
    value["project_root"] = str(store.project)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode(),
                create=not path.exists(), mode=0o600)
    return value


def _host(host: str | None) -> str | None:
    if host:
        return host
    if os.environ.get("CLAUDECODE"):
        return "claude-code"
    if os.environ.get("CODEX_THREAD_ID"):
        return "codex"
    return os.environ.get("AIVERYWHERE_HOST")


def _candidate(store: Store, host: str | None) -> tuple[str | None, str]:
    mapped = {"claude-code": "CLAUDE.md", "codex": "AGENTS.md",
              "dsh": "AGENTS.md"}.get(host or "")
    existing = [name for name in ("CLAUDE.md", "AGENTS.md", ".cursor/rules/aiverywhere.mdc")
                if (store.project / name).is_file()]
    if mapped and (store.project / mapped).is_file():
        return mapped, "existing"
    if existing:
        return existing[0], "existing"
    if mapped:
        return mapped, "create"
    return None, "no reliable host rule file"


def detect(store: Store, host: str | None = None) -> dict:
    host = _host(host)
    file, mode = _candidate(store, host)
    state = _state(store).get("host_adoption", {})
    enabled = False
    if file:
        path = store.project / file
        if path.is_file():
            text = path.read_text(errors="replace")
            enabled = BEGIN in text and END in text
    return {"project": str(store.project), "host": host, "file": file,
            "mode": mode, "supported": bool(file), "enabled": enabled,
            "state": state.get("status", "unanswered"),
            "block": BLOCK}


def _validate_file(store: Store, file: str) -> Path:
    if file not in ALLOWED:
        raise AdoptionError("不支持的宿主规则文件")
    target = (store.project / file).resolve()
    if not target.is_relative_to(store.project.resolve()):
        raise AdoptionError("宿主规则文件超出项目")
    if target.is_symlink():
        raise AdoptionError("不支持符号链接形式的宿主规则文件")
    return target


def enable(store: Store, file: str | None = None, host: str | None = None) -> dict:
    detected = detect(store, host)
    file = file or detected["file"]
    if not file:
        raise AdoptionError("当前项目没有可靠的自动加载入口")
    target = _validate_file(store, file)
    old = target.read_text() if target.is_file() else ""
    if old:
        before, marker, after = old.partition(BEGIN)
        if marker:
            _, end, remainder = after.partition(END)
            if not end:
                raise AdoptionError("已有 AIVERYWHERE 引导块缺少结束标记，请先人工检查")
            new = before.rstrip() + "\n\n" + BLOCK + remainder
        else:
            new = old.rstrip() + "\n\n" + BLOCK + "\n"
    else:
        new = BLOCK + "\n"
    with store.locked():
        current = target.read_text() if target.is_file() else ""
        if current != old:
            raise AdoptionError("宿主规则文件已被修改，请重新检查后再操作")
        atomic_write(target, new.encode(), create=not target.exists(), mode=0o644)
    checked = target.read_text()
    if checked.count(BEGIN) != 1 or checked.count(END) != 1:
        raise AdoptionError("写入后回读校验失败")
    _save(store, host_adoption={"status": "enabled", "file": file,
                                "host": _host(host), "updated": time.strftime(
                                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "sha256": hashlib.sha256(checked.encode()).hexdigest()})
    return {"project": str(store.project), "file": file, "created": not bool(old),
            "status": "enabled", "block": BLOCK}


def disable(store: Store) -> dict:
    state = _state(store).get("host_adoption", {})
    file = state.get("file") or detect(store).get("file")
    changed = False
    if file:
        target = _validate_file(store, file)
        if target.is_file():
            old = target.read_text()
            before, marker, after = old.partition(BEGIN)
            if marker:
                _, end, remainder = after.partition(END)
                if not end:
                    raise AdoptionError("已有 AIVERYWHERE 引导块缺少结束标记，请先人工检查")
                new = (before.rstrip() + "\n\n" + remainder.lstrip()).strip()
                new = (new + "\n") if new else ""
                with store.locked():
                    if target.read_text() != old:
                        raise AdoptionError("宿主规则文件已被修改，请重新检查后再操作")
                    atomic_write(target, new.encode(), mode=target.stat().st_mode & 0o777)
                changed = True
    _save(store, host_adoption={"status": "declined" if not changed else "disabled",
                                "file": file, "updated": time.strftime(
                                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return {"project": str(store.project), "file": file, "changed": changed,
            "status": "disabled"}


def status(store: Store) -> dict:
    detected = detect(store)
    detected["status"] = _state(store).get("host_adoption", {}).get("status", "unanswered")
    return detected
