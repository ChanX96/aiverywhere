"""Best-effort OS command isolation for delegated workers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path


def backend() -> str | None:
    if os.name == "posix" and shutil.which("sandbox-exec"):
        return "seatbelt"
    if shutil.which("bwrap"):
        return "bubblewrap"
    return None


@lru_cache(maxsize=1)
def available() -> bool:
    if backend() is None:
        return False
    with tempfile.TemporaryDirectory() as directory:
        try:
            command = wrap(Path(directory), [sys.executable, "-c", "pass"])
            probe = subprocess.run(command, capture_output=True, timeout=8)
        except (OSError, ValueError, subprocess.SubprocessError):
            return False
        return probe.returncode == 0


def _quote(value: Path) -> str:
    return str(value.resolve()).replace("\\", "\\\\").replace('"', '\\"')


def wrap(workspace: Path, argv: list[str], deny: tuple[Path, ...] = ()) -> list[str]:
    """Wrap argv so writes stay in workspace and instance data stays unreadable."""
    kind = backend()
    if kind is None:
        raise ValueError("当前系统没有可用的命令隔离后端")
    workspace = workspace.resolve()
    if kind == "seatbelt":
        profile = workspace / ".aiverywhere-sandbox.sb"
        paths = [workspace, Path(tempfile.gettempdir()), Path("/tmp"), Path("/private/tmp"),
                 Path("/dev/null")]
        rules = ["(version 1)", "(allow default)", "(deny file-write*)",
                 "(allow file-write* " + " ".join(f'(subpath "{_quote(path)}")' for path in paths) + ")"]
        if deny:
            rules.append("(deny file-read* " + " ".join(f'(subpath "{_quote(path)}")' for path in deny) + ")")
        profile.write_text("\n".join(rules) + "\n", encoding="utf-8")
        profile.chmod(0o600)
        return ["/usr/bin/sandbox-exec", "-f", str(profile), *argv]
    if kind == "bubblewrap":
        command = ["bwrap", "--ro-bind", "/", "/", "--bind", str(workspace), str(workspace),
                   "--tmpfs", "/tmp", "--dev", "/dev", "--proc", "/proc", "--chdir", str(workspace)]
        return [*command, *argv]
    raise ValueError("当前系统没有可用的命令隔离后端")
