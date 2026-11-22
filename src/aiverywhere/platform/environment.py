"""Bounded, passive observations. None of these observations grant capabilities."""

from __future__ import annotations

import os
import platform
import shutil
import sys

from ..core.store import Store


def inspect_environment(store: Store, entry: str, host: str | None, writable: bool,
                        mcp_servers: tuple[str, ...] = (), *, agent_edit: str | None = None,
                        exec_allowed: bool = False) -> dict:
    def checked(name: str) -> str:
        if len(name) > 100 or not name.isprintable():
            raise ValueError("宿主名称应为不超过 100 个字符的单行文本")
        return name

    if host:
        identity = {"name": checked(host), "source": "declared"}
    elif declared := os.environ.get("AIVERYWHERE_HOST"):
        identity = {"name": checked(declared), "source": "environment"}
    else:
        hints = [name for name, key in (("codex", "CODEX_THREAD_ID"), ("claude-code", "CLAUDECODE"))
                 if os.environ.get(key)]
        if len(hints) == 1:
            identity = {"name": hints[0], "source": "hint"}
        else:
            identity = {"name": None, "source": "ambiguous" if hints else "unknown"}
    markers = (".git", "pyproject.toml", "requirements.txt", "package.json", "Cargo.toml", "go.mod", "README.md")
    commands = ("git", "python3", "node", "launchctl", "systemctl", "crontab")
    return {
        "entry": entry,
        "execution": "host_worker" if host else "local_process",
        "host": identity,
        "system": platform.system(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "terminal": bool(sys.stdin and sys.stdin.isatty()),
        "project_root": str(store.project),
        "instance_root": str(store.home),
        "project_markers": [name for name in markers if (store.project / name).exists()],
        "commands_on_path": [name for name in commands if shutil.which(name)],
        "grants": {"project_read": True, "project_write": writable, "command_exec": exec_allowed,
                   "mcp_servers": list(mcp_servers), "agent_edit_revision": agent_edit},
        "unverified": ["browser_access", "unattended_wakeup"],
    }
