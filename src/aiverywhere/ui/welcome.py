"""Terminal welcome screen. The wordmark is generated, never hand-assembled."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

from .. import __version__
from ..core.store import Store, skill_revision, skill_text

WORDMARK = "AIVERYWHERE"
# 5x7 block font. Rows are joined from this map, so the spelling is checked by
# the constant and the tests rather than by a hand-copied ASCII sketch.
FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
}


def _color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _color() else text


def _truecolor() -> bool:
    return _color() and os.environ.get("COLORTERM", "").lower() in {"truecolor", "24bit"}


def _gradient(text: str, row: int) -> str:
    if not _truecolor():
        return _paint("1;36", text)
    start, end = (121, 229, 195), (142, 161, 255)
    parts = []
    for index, char in enumerate(text):
        if char == " ":
            parts.append(char)
            continue
        fraction = min(1.0, (index / max(1, len(text) - 1)) * 0.85 + row * 0.02)
        red, green, blue = (round(a + (b - a) * fraction) for a, b in zip(start, end))
        parts.append(f"\033[38;2;{red};{green};{blue}m{char}")
    return "".join(parts) + "\033[0m"


def _wordmark() -> list[str]:
    rows = []
    for row in range(7):
        line = " ".join(
            "".join("█" if bit == "1" else " " for bit in FONT[letter][row])
            for letter in WORDMARK)
        rows.append("  " + _gradient(line, row))
    return rows


def _line(label: str, value: str) -> str:
    return f"  {_paint('2', label)}{' ' * max(1, 8 - len(label))} {value}"


def _compact_path(path: Path) -> str:
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def _model_description(model: dict) -> str:
    if not model:
        return "未配置；CLI 模式请运行 aiverywhere setup"
    description = model.get("model") or "未配置"
    if model.get("base_url"):
        host = urlsplit(model["base_url"]).hostname
        if host:
            description += f"  @ {host}"
    if any(model.get(key) for key in ("api_key", "auth_token", "api_key_env", "auth_token_env")):
        description += "  · 凭据已配置"
    if model.get("max_tokens"):
        description += f"  · {model['max_tokens']} tokens"
    return description


def render(store: Store) -> str:
    initialized = store.data.is_dir()
    columns = shutil.get_terminal_size((80, 24)).columns
    rule = "  " + _paint("2", "─" * max(20, min(columns - 4, 68)))
    lines = [""]
    if columns >= 72:
        lines += _wordmark()
        lines.append("")
    else:
        lines.append("  " + _paint("1;36", "AIVERYWHERE") + _paint("2", "   aiverywhere"))
    lines.append("  " + _paint("1", "aiverywhere") + _paint("2", f"  {__version__}")
                 + _paint("2", "   a small shell over an LLM"))
    lines.append(rule)

    if not initialized:
        lines += [
            _line("状态", "尚未初始化"),
            "",
            "  运行 aiverywhere init 和 aiverywhere setup 后再开始。",
            "",
        ]
        return "\n".join(lines)

    model = {}
    try:
        model = store.configuration().get("model", {})
    except (OSError, ValueError):
        model = {}
    try:
        revision = skill_revision(skill_text(store.home))[:8]
    except (OSError, ValueError):
        revision = "不可读取"
    try:
        items = store.memory_items()
    except (OSError, ValueError):
        items = []
    clues = sum(item.get("kind") == "clue" for item in items)
    lines += [
        _line("模式", "CLI" if model else "宿主模式（使用宿主模型）"),
        _line("项目", _compact_path(store.project)),
        _line("实例", _compact_path(store.home)),
        _line("模型", _model_description(model)),
        _line("Agent", revision),
        _line("记忆", f"{len(items) - clues} 条事实/技能  ·  {clues} 条线索"),
        _line("访问", "网页可用 · worker 可用；--allow-write 写入 · --allow-exec 命令"),
        rule,
        "  " + _paint("1;36", "›") + " 输入任务开始"
        + _paint("2", "   /help 帮助 · /cancel 取消 · /quit 退出"),
        "  " + _paint("2", "aiverywhere run '...'  ·  aiverywhere web  ·  aiverywhere skill --info"),
        "",
    ]
    return "\n".join(lines)


def show(store: Store) -> bool:
    print(render(store), flush=True)
    return store.data.is_dir()
