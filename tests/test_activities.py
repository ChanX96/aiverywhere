import asyncio
import tempfile
import unittest
from pathlib import Path

from aiverywhere.core.agent import Task
from aiverywhere.core.store import Store


class ActivitiesAndTodos(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = root / "project"
        self.project.mkdir()
        self.store = Store(root / "instance", self.project)
        self.store.initialize()

    def test_skill_tool_mcp_activity_and_todo_state(self):
        class Remote:
            selected = {"mcp_ping": ("demo", "ping")}

            async def call(self, name, values):
                return {"pong": True}

        class Provider:
            async def agentloop(self, task, environment, messages, prompt, max_turns,
                                checkpoint, **kwargs):
                remote = Remote()
                async def call(ident, name, values):
                    return await task._tool_result(
                        {"id": ident, "name": name, "input": values}, remote)
                await call("a", "read_skill", {"module": "plan"})
                await call("b", "todo", {"action": "set", "items": ["检查输入", "完成修改"]})
                await call("c", "mcp_ping", {})
                await call("d", "todo", {"action": "update", "id": "t1", "status": "completed"})
                return "完成", messages + [{"role": "assistant", "content": "完成"}]

        task = Task(self.store)
        asyncio.run(task.run("大任务", Provider(), max_turns=2, timeout=5))
        self.assertEqual(task.status, "completed")
        kinds = [(item["kind"], item["name"], item["status"]) for item in task.activities]
        self.assertIn(("skill", "read_skill", "ok"), kinds)
        self.assertIn(("tool", "todo", "ok"), kinds)
        self.assertIn(("mcp", "mcp_ping", "ok"), kinds)
        self.assertEqual([item["status"] for item in task.todos], ["completed", "pending"])
        result = task.result()
        self.assertEqual(result["todos"][0]["text"], "检查输入")
        self.assertEqual(len(result["activities"]), 4)

    def test_activity_callback_failure_does_not_break_tool(self):
        class Provider:
            async def agentloop(self, task, environment, messages, prompt, max_turns,
                                checkpoint, **kwargs):
                remote = type("Remote", (), {"selected": {}})()
                await task._tool_result({"id": "x", "name": "list_files",
                                         "input": {"path": "."}}, remote)
                return "完成", messages

        task = Task(self.store)
        task.activity_callback = lambda event: (_ for _ in ()).throw(RuntimeError("ui down"))
        asyncio.run(task.run("列目录", Provider(), max_turns=2, timeout=5))
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.activities[0]["status"], "ok")

    def test_todo_tool_validates_and_lists(self):
        task = Task(self.store)
        out = task.tools.execute("todo", {"action": "set", "items": ["一", "二"]})
        self.assertEqual(out["total"], 2)
        out = task.tools.execute("todo", {"action": "update", "id": "t2",
                                          "status": "completed"})
        self.assertEqual(out["completed"], 1)
        self.assertEqual(task.tools.execute("todo", {"action": "list"})["total"], 2)
        with self.assertRaises(ValueError):
            task.tools.execute("todo", {"action": "update", "id": "missing",
                                        "status": "completed"})
