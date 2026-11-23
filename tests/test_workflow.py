import subprocess
import tempfile
import unittest
from pathlib import Path

from aiverywhere.core import workflow
from aiverywhere.core.store import Store


class WorkflowModules(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = root / "project"
        self.project.mkdir()
        self.store = Store(self.project / ".aiverywhere", self.project)
        self.store.initialize()

    def override(self, name: str, text: str):
        path = workflow.override_dir(self.store) / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_default_modules_and_project_override(self):
        rows = workflow.list_modules(self.store)
        self.assertEqual([row["name"] for row in rows], list(workflow.MODULES))
        self.assertTrue(all(row["source"] == "default" for row in rows))
        self.override("extract", "# extract\n契约版本 1\n\n## 做法\n\n只保存经过两次验证的技能。\n")
        loaded = workflow.load_module(self.store, "extract")
        self.assertEqual(loaded["source"], "override")
        self.assertIn("两次验证", loaded["text"])
        self.assertEqual(workflow.load_module(self.store, "plan")["source"], "default")

    def test_incompatible_override_and_fixed_finish(self):
        self.override("plan", "# plan\n契约版本 2\n")
        row = next(row for row in workflow.list_modules(self.store) if row["name"] == "plan")
        self.assertFalse(row["compatible"])
        with self.assertRaises(workflow.WorkflowError):
            workflow.load_module(self.store, "plan")
        finish = self.override("finish", "# finish\n契约版本 1\n\n## 做法\n\n放宽写入。\n")
        rows = workflow.list_modules(self.store)
        finish_row = next(row for row in rows if row["name"] == "finish")
        self.assertEqual(finish_row["source"], "default")
        self.assertEqual(finish_row["ignored_override"], str(finish))
        self.assertNotIn("放宽写入", workflow.load_module(self.store, "finish")["text"])

    def test_host_only_path_helper_reports_same_project_key(self):
        source = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["sh", str(source / "skills/aiverywhere/scripts/workflow-path.sh"),
             "--project", str(self.project), "--home", str(self.store.home)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"project_key={self.store.memory.key}", result.stdout)
        self.assertIn(f"overrides={workflow.override_dir(self.store)}", result.stdout)
        self.assertIn("default=", result.stdout)

    def test_reinstall_keeps_override(self):
        path = self.override("recall", "# recall\n契约版本 1\n\n## 做法\n\n先查项目摘要。\n")
        self.store.initialize()
        self.assertTrue(path.is_file())
        self.assertIn("先查项目摘要", workflow.load_module(self.store, "recall")["text"])


class RequiredMemory(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = root / "project"
        self.project.mkdir()
        self.store = Store(self.project / ".aiverywhere", self.project)
        self.store.initialize()

    class Provider:
        def __init__(self, save: bool):
            self.save = save

        async def agentloop(self, task, environment, messages, prompt, max_turns,
                            checkpoint, **kwargs):
            remote = type("Remote", (), {"selected": {}})()

            async def call(name, values):
                await task._tool_result({"id": name, "name": name, "input": values}, remote)

            await call("require_memory", {"kind": "fact", "title": "月报默认单位"})
            if self.save:
                await call("remember", {
                    "kind": "fact", "title": "月报默认单位", "text": "以后默认用万元。"})
            return "业务完成", messages + [{"role": "assistant", "content": "业务完成"}]

    def run_task(self, save):
        import asyncio
        from aiverywhere.core.agent import Task

        task = Task(self.store)
        asyncio.run(task.run("更新月报并记住单位", self.Provider(save), max_turns=2, timeout=5))
        return task

    def test_missing_required_memory_marks_partial(self):
        task = self.run_task(False)
        self.assertEqual(task.status, "partial")
        self.assertEqual(task.memory_state, "pending")
        self.assertIn("必记项未确认", task.warning)

    def test_confirmed_required_memory_completes(self):
        task = self.run_task(True)
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.memory_state, "confirmed")
        self.assertEqual(task.result()["required_memory"][0]["title"], "月报默认单位")

    def test_read_skill_tool_reads_modules_without_project_access(self):
        from aiverywhere.core.agent import Task
        from aiverywhere.core.workflow import load_module

        task = Task(self.store)
        loaded = task.tools.execute("read_skill", {"module": "plan"})
        self.assertEqual(loaded["source"], "default")
        self.assertIn("职责与触发", loaded["text"])
        self.assertEqual(load_module(self.store, "finish")["contract"], 1)
        worker = Task(self.store, entry="worker")
        self.assertNotIn("read_skill", worker.tools.active)

    def test_finish_agent_file_cannot_be_written(self):
        with self.assertRaises(PermissionError):
            self.store.write_agent_file(
                "references/workflow/finish.md", "# changed\n", "new")

    def test_remember_tool_can_correct_by_id(self):
        from aiverywhere.core.agent import Task

        first = self.store.remember("月报单位", "默认用元。", "fact", "acceptance")
        task = Task(self.store)
        updated = task.tools.execute("remember", {
            "id": first["id"], "revision": 1, "kind": "fact",
            "title": "月报单位", "text": "默认用万元。"})
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(self.store.recall(first["id"])["text"], "默认用万元。")

    def test_worker_cannot_write_shared_memory(self):
        from aiverywhere.core.agent import Task

        worker = Task(self.store, entry="worker", memory_writable=False)
        self.assertNotIn("remember", worker.tools.active)
        self.assertNotIn("require_memory", worker.tools.active)
        with self.assertRaises(PermissionError):
            worker.tools.execute("remember", {
                "kind": "fact", "title": "越权", "text": "不应写入"})
