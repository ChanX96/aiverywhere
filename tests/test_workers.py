import asyncio
import tempfile
import unittest
from pathlib import Path

from aiverywhere.core.agent import Task
from aiverywhere.core.store import Store


class Provider:
    async def agentloop(self, task, environment, messages, prompt, max_turns, checkpoint):
        if task.allow_workers:
            return str(await task.delegate(["生成 a.txt", "生成 b.txt"])), messages
        name = "a.txt" if "a.txt" in prompt else "b.txt"
        task.tools.execute("write_file", {"path": name, "text": "from " + name, "expected": "new"})
        return "wrote " + name, messages


class WorkersTest(unittest.TestCase):
    def test_workers_write_private_workspaces_and_return_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            (project / "README.md").write_text("source")
            store = Store(root / "instance", project)
            store.initialize()
            events = []

            async def run():
                task = Task(store, writable=True, allow_workers=True)
                task.worker_callback = events.append
                await task.run("parent", Provider(), max_turns=4, timeout=10)
                return task

            task = asyncio.run(run())
            self.assertEqual(task.status, "completed")
            self.assertFalse((project / "a.txt").exists())
            self.assertEqual({item["status"] for item in events}, {"started", "completed"})
            self.assertEqual(len(task.artifacts), 2)
            artifact = next(item for item in task.artifacts.values() if item["path"] == "a.txt")
            accepted = task.accept_artifact(artifact["id"], "out.txt", "new")
            self.assertEqual((project / "out.txt").read_text(), "from a.txt")
            self.assertEqual(accepted["sha256"], artifact["sha256"])


if __name__ == "__main__":
    unittest.main()
