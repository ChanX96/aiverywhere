"""Ten fixed acceptance scenarios exercised through CLI and host-only paths."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from aiverywhere.core.agent import Task
from aiverywhere.core.store import Store

ROOT = Path(__file__).resolve().parents[1]


class AcceptanceMatrix(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cli_project = self.root / "cli-project"
        self.cli_project.mkdir()
        self.cli_instance = self.cli_project / ".aiverywhere"
        self.cli_store = Store(self.cli_instance, self.cli_project)
        self.cli_store.initialize()
        self.host_project = self.root / "host-project"
        self.host_project.mkdir()
        self.host_instance = self.root / "host-instance"
        (self.root / "host-home").mkdir()
        self.host_env = self._env(self.root / "host-home")
        self.host_env["AIVERYWHERE_HOME"] = str(self.host_instance)
        self._install_host()

    @staticmethod
    def _env(home: Path) -> dict:
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PYTHONPATH"] = str(ROOT / "src") + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        return env

    def _install_host(self):
        result = subprocess.run(
            ["sh", str(ROOT / "install.sh"), "--yes", "--no-cli",
             "--project", str(self.host_project), "--home", str(self.host_instance)],
            cwd=self.host_project, env=self.host_env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _cli(self, *args, check=True):
        result = subprocess.run(
            [sys.executable, "-m", "aiverywhere", "--home", str(self.cli_instance),
             "--project", str(self.cli_project), *args],
            cwd=self.cli_project, env=self._env(self.root / "cli-home"),
            capture_output=True, text=True, timeout=30)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result

    def _host_script(self, name: str, *args, check=True):
        result = subprocess.run(
            ["sh", str(self.host_instance / "skills/aiverywhere/scripts" / name), *args],
            cwd=self.host_project, env=self.host_env, capture_output=True, text=True, timeout=20)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result

    def _host_write(self, title: str, text: str, *extra: str):
        result = self._host_script(
            "write-memory.sh", "--kind", "fact", "--title", title, "--text", text,
            "--source", "acceptance", *extra)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def _host_read(self, ident: str) -> dict:
        return json.loads(self._host_script("read-memory.sh", ident).stdout)

    def _cli_write(self, title: str, text: str, *extra: str):
        result = self._cli("memory", "put", title, text, "--kind", "fact", *extra)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def _cli_read(self, ident: str) -> dict:
        return json.loads(self._cli("memory", "get", ident).stdout)

    def _memory_files(self) -> list[Path]:
        return sorted((self.cli_instance / "data/memory").rglob("*.json"))

    class TextProvider:
        def __init__(self):
            self.calls = 0

        async def agentloop(self, task, environment, messages, prompt, max_turns,
                            checkpoint, **kwargs):
            self.calls += 1
            return "简单回答", messages + [{"role": "assistant", "content": "简单回答"}]

    class RequiredProvider:
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

    class ArtifactProvider:
        async def agentloop(self, task, environment, messages, prompt, max_turns,
                            checkpoint, **kwargs):
            task.tools.execute("write_file", {
                "path": "artifact.md", "text": "acceptance artifact\\n", "expected": "new"})
            remote = type("Remote", (), {"selected": {}})()

            async def call(name, values):
                await task._tool_result({"id": name, "name": name, "input": values}, remote)

            await call("require_memory", {"kind": "fact", "title": "产物约定"})
            await call("remember", {
                "kind": "fact", "title": "产物约定", "text": "验收产物在该项目中。"})
            return "产物已生成", messages + [{"role": "assistant", "content": "产物已生成"}]

    def test_01_fresh_install_and_workflow_discovery(self):
        listed = json.loads(self._cli("workflow", "list").stdout)
        self.assertEqual([row["name"] for row in listed],
                         ["plan", "recall", "execute", "extract", "finish"])
        self.assertTrue(all(row["source"] == "default" for row in listed))
        workflow = self.host_instance / "skills/aiverywhere/references/workflow"
        self.assertEqual(sorted(path.stem for path in workflow.glob("*.md")),
                         ["execute", "extract", "finish", "plan", "recall"])
        self.assertTrue((self.host_project / ".agents/skills/aiverywhere").is_symlink())
        self.assertFalse((self.host_instance / "venv").exists())
        path = self._host_script(
            "workflow-path.sh", "--project", str(self.host_project), "--home", str(self.host_instance))
        self.assertIn("project_key=", path.stdout)
        self.assertIn("default=", path.stdout)
        self.assertIn("overrides=", path.stdout)

    def test_02_explicit_project_fact_readback(self):
        cli = self._cli_write("本项目月报单位", "本项目月报默认用万元。")
        host = self._host_write("本项目月报单位", "本项目月报默认用万元。")
        self.assertEqual(cli["kind"], "fact")
        self.assertEqual(host["kind"], "fact")
        self.assertEqual(self._cli_read(cli["id"])["text"], "本项目月报默认用万元。")
        self.assertEqual(self._host_read(host["id"])["revision"], 1)

    def test_03_one_time_or_do_not_remember(self):
        before = len(self._memory_files())
        provider = self.TextProvider()
        task = Task(self.cli_store)
        asyncio.run(task.run("这次用元，不要记。", provider, max_turns=2, timeout=5))
        self.assertEqual(task.status, "completed")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(len(self._memory_files()), before)
        host_before = sorted((self.host_instance / "data/memory").rglob("*.json"))
        self.assertEqual(host_before, [])

    def test_04_correct_existing_fact_and_conflict(self):
        cli = self._cli_write("月报单位", "默认用元。")
        updated = self._cli_write(
            "月报单位", "默认用万元。", "--id", cli["id"], "--revision", "1")
        self.assertEqual(updated["revision"], 2)
        stale = self._cli("memory", "put", "月报单位", "默认用亿元。", "--kind", "fact",
                          "--id", cli["id"], "--revision", "1", check=False)
        self.assertNotEqual(stale.returncode, 0)
        self.assertEqual(self._cli_read(cli["id"])["revision"], 2)

        host = self._host_write("月报单位", "默认用元。")
        host_updated = self._host_write(
            "月报单位", "默认用万元。", "--id", host["id"], "--revision", "1")
        self.assertEqual(host_updated["revision"], 2)
        stale = self._host_script(
            "write-memory.sh", "--kind", "fact", "--title", "月报单位", "--text", "默认用亿元。",
            "--source", "acceptance", "--id", host["id"], "--revision", "1", check=False)
        self.assertNotEqual(stale.returncode, 0)
        self.assertEqual(self._host_read(host["id"])["revision"], 2)

    def test_05_memory_failure_is_not_reported_complete(self):
        task = Task(self.cli_store)
        asyncio.run(task.run(
            "记住月报单位", self.RequiredProvider(False), max_turns=3, timeout=5))
        self.assertEqual(task.status, "partial")
        self.assertEqual(task.memory_state, "pending")

        host = self._host_write("只读前记录", "保留旧值。")
        memory_dir = next((self.host_instance / "data/memory").rglob(f"{host['id']}.json")).parent
        try:
            memory_dir.chmod(0o500)
            failed = self._host_script(
                "write-memory.sh", "--kind", "fact", "--title", "只读新记录",
                "--text", "不能写入。", "--source", "acceptance", check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("not writable", failed.stderr)
        finally:
            memory_dir.chmod(0o700)
        self.assertEqual(self._host_read(host["id"])["text"], "保留旧值。")

    def test_06_project_override_compatibility_and_reinstall(self):
        override = self.cli_instance / "overrides/default/workflow/extract.md"
        override.parent.mkdir(parents=True)
        override.write_text("# extract\n契约版本 1\n\n## 做法\n\n只保存双样本验证的技能。\n")
        shown = json.loads(self._cli("workflow", "show", "extract").stdout)
        self.assertEqual(shown["source"], "override")
        self.assertIn("双样本", shown["text"])
        incompatible = override.parent / "plan.md"
        incompatible.write_text("# plan\n契约版本 2\n")
        failed = self._cli("workflow", "show", "plan", check=False)
        self.assertNotEqual(failed.returncode, 0)

        path = self._host_script(
            "workflow-path.sh", "--project", str(self.host_project), "--home", str(self.host_instance))
        key = next(line.split("=", 1)[1] for line in path.stdout.splitlines()
                   if line.startswith("project_key="))
        host_override = self.host_instance / "overrides" / key / "workflow/extract.md"
        host_override.parent.mkdir(parents=True)
        host_override.write_text("# extract\n契约版本 1\n\n## 做法\n\n只保存双样本验证的技能。\n")
        self._install_host()
        self.assertTrue(host_override.is_file())
        self.assertIn("双样本", host_override.read_text())

    def test_07_simple_task_has_no_memory_or_worker_side_effects(self):
        before = list(self._memory_files())
        provider = self.TextProvider()
        task = Task(self.cli_store)
        asyncio.run(task.run("你好", provider, max_turns=2, timeout=5))
        self.assertEqual(task.status, "completed")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(list(self._memory_files()), before)
        self.assertEqual(task.trace, [])
        self.assertEqual(task.worker_tasks, {})
        self.assertEqual(sorted((self.host_instance / "data/memory").rglob("*.json")), [])
        self.assertEqual([path for path in (self.host_instance / "data/logs").rglob("*")
                          if path.is_file()], [])

    def test_08_new_process_and_project_isolation(self):
        record = self._cli_write("跨进程事实", "新进程应能读回。")
        again = self._cli_read(record["id"])
        self.assertEqual(again["text"], "新进程应能读回。")
        (self.root / "other-project").mkdir()
        other = Store(self.root / "other-instance", self.root / "other-project")
        other.initialize()
        self.assertEqual(other.search("跨进程", "fact"), [])

        host = self._host_write("跨进程事实", "新进程应能读回。")
        self.assertEqual(json.loads(self._host_script(
            "read-memory.sh", host["id"]).stdout)["text"], "新进程应能读回。")

    def test_09_worker_cannot_write_shared_memory(self):
        worker = Task(self.cli_store, entry="worker")
        self.assertNotIn("remember", worker.tools.active)
        self.assertNotIn("require_memory", worker.tools.active)
        with self.assertRaises(PermissionError):
            worker.tools.execute("remember", {
                "kind": "fact", "title": "越权", "text": "不能写。"})
        # Host mode has no worker runtime; it must leave the same zero-write baseline.
        self.assertEqual(sorted((self.host_instance / "data/memory").rglob("*.json")), [])

    def test_10_end_to_end_artifact_memory_and_receipt(self):
        task = Task(self.cli_store, writable=True)
        asyncio.run(task.run(
            "生成产物并记住约定", self.ArtifactProvider(), max_turns=4, timeout=5))
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.memory_state, "confirmed")
        self.assertTrue((self.cli_project / "artifact.md").is_file())
        self.assertEqual(self._cli_read(task.receipts[-1]["entry_id"])["revision"], 1)

        host_artifact = self.host_project / "artifact.md"
        host_artifact.write_text("acceptance artifact\n")
        host = self._host_write("产物约定", "验收产物在该项目中。")
        self.assertTrue(host_artifact.is_file())
        self.assertEqual(self._host_read(host["id"])["text"], "验收产物在该项目中。")


if __name__ == "__main__":
    unittest.main()
