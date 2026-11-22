"""Context budgeting and automatic compaction for the stable agent loop."""

from __future__ import annotations

import json
from typing import Callable

from .store import Store


DEFAULTS = {
    "max_context_tokens": 64000,
    "compact_at": 0.8,
    "keep_recent_turns": 6,
    "summary_max_chars": 4000,
}


class ContextOverflow(ValueError):
    """The request cannot fit even after a safe compaction."""


def estimate_tokens(value) -> int:
    """Conservative, dependency-free estimate for English and CJK text."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    cjk = sum(1 for char in text if "\u3400" <= char <= "\u9fff")
    return max(1, (len(text) - cjk) // 4 + cjk // 2)


def _text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_text(value.get(key, "")) for key in ("text", "content", "thinking"))
    return str(value)


def _prompt(message: dict) -> bool:
    content = message.get("content")
    return message.get("role") == "user" and isinstance(content, str)


def _tool_result(message: dict) -> bool:
    content = message.get("content")
    return (message.get("role") == "user" and isinstance(content, list)
            and any(isinstance(item, dict) and item.get("type") == "tool_result"
                    for item in content))


class ContextManager:
    def __init__(self, store: Store, provider, *, summary: dict | None = None,
                 settings: dict | None = None,
                 on_summary: Callable[[str, str, int], None] | None = None):
        self.store = store
        self.provider = provider
        self.settings = {**DEFAULTS, **(settings or {})}
        self.summary = (summary or {}).get("text", "")
        self.covered = int((summary or {}).get("covers_messages", 0) or 0)
        self.compactions = 0
        self.on_summary = on_summary

    @property
    def max_tokens(self) -> int:
        return int(self.settings["max_context_tokens"])

    @property
    def trigger(self) -> int:
        return max(1, int(self.max_tokens * float(self.settings["compact_at"])))

    def context_view(self, messages: list) -> list:
        if not self.summary:
            return messages
        prefix = {"role": "user", "content": "[Earlier conversation summary]\n" + self.summary}
        return [prefix, *messages[self.covered:]]

    def estimate(self, system: str, messages: list, tools: list = ()) -> int:
        return estimate_tokens({"system": system, "messages": messages, "tools": list(tools)})

    def _split(self, messages: list) -> int | None:
        keep = max(2, int(self.settings["keep_recent_turns"]) * 2)
        split = min(len(messages) - 1, max(1, len(messages) - keep))
        if split <= self.covered:
            return None
        # Start at a real user prompt, never between tool_use and tool_result.
        while split > self.covered and not _prompt(messages[split]):
            split -= 1
        if split <= self.covered:
            return None
        return split

    async def _model_summary(self, old: list, previous: str) -> str:
        provider = self.provider() if callable(self.provider) else self.provider
        send = getattr(provider, "send", None)
        if send is None:
            raise ValueError("当前执行器不支持摘要请求")
        system = (
            "You compact an ongoing agent conversation. Return only a concise continuation "
            "summary. Preserve the user's goal and constraints, confirmed decisions, evidence, "
            "file paths, memory IDs, open questions, and unfinished work. Do not invent facts, "
            "do not call tools, and do not include hidden reasoning."
        )
        previous_block = f"Previous summary:\n{previous}\n\n" if previous else ""
        payload = json.dumps(old, ensure_ascii=False)[:50000]
        data = await send(system, [{"role": "user", "content": previous_block + "Messages:\n" + payload}], [])
        content = data.get("content") if isinstance(data, dict) else None
        if not isinstance(content, list):
            raise ValueError("摘要响应格式不正确")
        text = "\n".join(block.get("text", "") for block in content
                         if isinstance(block, dict) and block.get("type") == "text").strip()
        if not text:
            raise ValueError("摘要响应为空")
        return text[:int(self.settings["summary_max_chars"])]

    def _fallback_summary(self, old: list, previous: str) -> str:
        lines = []
        if previous:
            lines.append(previous)
        for message in old:
            content = message.get("content")
            role = message.get("role", "?")
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    kind = item.get("type", "")
                    if kind == "text":
                        lines.append(f"{role}: {_text(item.get('text', ''))[:500]}")
                    elif kind == "tool_use":
                        lines.append(f"tool_use: {item.get('name', '')} {json.dumps(item.get('input', {}), ensure_ascii=False)[:300]}")
                    elif kind == "tool_result":
                        lines.append(f"tool_result: {_text(item.get('content', ''))[:500]}")
                    else:
                        lines.append(f"{role}/{kind}: {_text(item)[:300]}")
            else:
                lines.append(f"{role}: {_text(content)[:500]}")
        text = "\n".join(line for line in lines if line).strip()
        return text[:int(self.settings["summary_max_chars"])] or "Earlier turns were compacted."

    async def view(self, system: str, messages: list, tools: list = ()) -> list:
        if self.estimate(system, self.context_view(messages), tools) <= self.trigger:
            view = self.context_view(messages)
            if self.estimate(system, view, tools) > self.max_tokens:
                raise ContextOverflow("上下文超过模型上限，且没有足够的旧回合可安全压实")
            return view
        split = self._split(messages)
        if split is None:
            view = self.context_view(messages)
            if self.estimate(system, view, tools) > self.max_tokens:
                raise ContextOverflow("上下文超过模型上限，且没有足够的旧回合可安全压实")
            return view
        old = messages[self.covered:split]
        method = "model"
        try:
            text = await self._model_summary(old, self.summary)
        except Exception:
            method = "deterministic"
            text = self._fallback_summary(old, self.summary)
        if not text:
            raise ContextOverflow("压缩摘要为空，拒绝静默丢弃上下文")
        self.summary = text
        self.covered = split
        self.compactions += 1
        if self.on_summary is not None:
            self.on_summary(text, method, split)
        view = self.context_view(messages)
        if self.estimate(system, view, tools) > self.max_tokens:
            raise ContextOverflow("压缩后上下文仍超过模型上限")
        return view

    async def force(self, system: str, messages: list, tools: list = ()) -> list:
        split = self._split(messages)
        if split is None:
            raise ContextOverflow("没有可安全压实的完整旧回合")
        old = messages[self.covered:split]
        method = "model"
        try:
            text = await self._model_summary(old, self.summary)
        except Exception:
            method = "deterministic"
            text = self._fallback_summary(old, self.summary)
        self.summary = text
        self.covered = split
        self.compactions += 1
        if self.on_summary is not None:
            self.on_summary(text, method, split)
        return self.context_view(messages)
