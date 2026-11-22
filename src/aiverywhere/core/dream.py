"""One ordinary task over the clue inbox. There is no dedicated Dream loop or state."""

from __future__ import annotations

import json

from .agent import Messages, Native, Task, executor
from .store import Store


def pending_clues(store: Store, limit: int = 20) -> list:
    """Read-only summaries of unresolved clues; the model expands text by ID."""
    return store.search("", "clue", cold=True, limit=limit)


def has_clues(store: Store) -> bool:
    return bool(pending_clues(store, limit=1))


async def dream(store: Store, provider: Messages | Native | None = None, *, client=None, model=None,
                budget: int = 60, host: str | None = None) -> dict:
    """Run one ordinary task over the clue inbox. No lease, claim, or JSON lesson contract."""
    clues = pending_clues(store)
    if not clues:
        return {"status": "idle", "model_calls": 0}
    task = Task(store, entry="dream", host=host)
    prompt = (
        "执行一次空闲 Dream。待处理线索（摘要；需要正文时用 recall 按 ID 展开）：\n"
        + json.dumps(clues, ensure_ascii=False)
        + "\n按 SKILL.md 的空闲 Dream 约定处理：逐条自问现象与证据、是否可复用、适用条件和验证依据；"
        "证据足够才用 remember 写入 fact 或 skill，不要新增 clue；已处理的线索用 clue_done 标记；"
        "证据不足就保留线索并结束。"
    )
    await task.run(prompt, provider or executor(client, model, store), max_turns=6, timeout=budget)
    return task.result()
