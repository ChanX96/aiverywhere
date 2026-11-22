import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from aiverywhere.core.dream import dream, has_clues, pending_clues
from aiverywhere.core.store import Store
from aiverywhere.core.tools import Tools


class Provider:
    def __init__(self, store, clue_id):
        self.store = store
        self.clue_id = clue_id
        self.prompt = ""
        self.tools = []

    async def agentloop(self, task, environment, messages, prompt, max_turns, checkpoint):
        self.prompt = prompt
        self.tools = sorted(task.tools.active)
        task.tools.execute("remember", {
            "kind": "skill", "title": "核对公式位置", "text": "导出后逐格核对公式位置。"})
        task.tools.execute("clue_done", {"id": self.clue_id})
        return "Dream completed", messages


class Dream(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = Store(self.root / "install", self.project)
        self.store.initialize()

    def test_clue_is_memory_and_dream_is_one_ordinary_task(self):
        clue = self.store.remember("线索：公式位置", "数量正确但公式位置错误。", "clue", "user")
        self.assertEqual(self.store.search("公式", "clue")[0]["id"], clue["id"])
        self.assertEqual(self.store.search("公式", "fact"), [])
        self.assertTrue(has_clues(self.store))
        provider = Provider(self.store, clue["id"])
        result = asyncio.run(dream(self.store, provider))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["answer"], "Dream completed")
        self.assertIn(clue["id"], provider.prompt)
        self.assertTrue({"remember", "clue_done", "recall"} <= set(provider.tools))
        self.assertNotIn("write_file", provider.tools)
        self.assertEqual(pending_clues(self.store), [])
        self.assertEqual(self.store.search("公式", "skill")[0]["title"], "核对公式位置")

    def test_no_clues_makes_no_model_call(self):
        result = asyncio.run(dream(self.store))
        self.assertEqual(result, {"status": "idle", "model_calls": 0})

    def test_dream_tools_cannot_delete_facts_and_normal_tasks_cannot_resolve_clues(self):
        clue = self.store.remember("线索：待核对", "需要核对。", "clue", "user")
        fact = self.store.remember("事实", "不应被 Dream 删除。", "fact", "user")
        normal = Tools(self.store, "normal", writable=True)
        self.assertNotIn("clue_done", normal.available)
        self.assertNotIn("clue_done", normal.active)
        limited = Tools(self.store, "dream", read_only=True)
        self.assertIn("clue_done", limited.active)
        self.assertNotIn("write_file", limited.available)
        limited.execute("clue_done", {"id": clue["id"]})
        self.assertFalse(has_clues(self.store))
        with self.assertRaises(ValueError):
            limited.execute("clue_done", {"id": fact["id"]})

    def test_clues_do_not_expire_like_old_memory(self):
        clue = self.store.remember("线索：旧问题", "三个月前的未解问题。", "clue", "user")
        path = self.store.memory.root / f"{clue['id']}.json"
        record = json.loads(path.read_text())
        record["updated"] = "2025-01-01T00:00:00Z"
        path.write_text(json.dumps(record, ensure_ascii=False))
        self.assertEqual(self.store.search("", "clue")[0]["id"], clue["id"])


class CommandLine(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.home = self.root / "install"
        self.source = Path(__file__).resolve().parents[1] / "src"

    def cli(self, *args):
        env = dict(os.environ, PYTHONPATH=str(self.source), AIVERYWHERE_MODEL="",
                   ANTHROPIC_MODEL="", ANTHROPIC_BASE_URL="", ANTHROPIC_API_KEY="", ANTHROPIC_AUTH_TOKEN="")
        return subprocess.run([sys.executable, "-m", "aiverywhere", "--home", str(self.home),
                               "--project", str(self.project), *args],
                              cwd=self.project, env=env, text=True, capture_output=True, check=False)

    def test_host_can_record_list_read_and_resolve_clues(self):
        put = self.cli("memory", "put", "--kind", "clue", "线索：月报", "公式位置错误")
        self.assertEqual(put.returncode, 0, put.stderr)
        entry = json.loads(put.stdout)
        listing = self.cli("memory", "search", "--kind", "clue")
        self.assertEqual(json.loads(listing.stdout)[0]["id"], entry["id"])
        self.assertIn("公式位置错误", json.loads(self.cli("memory", "get", entry["id"]).stdout)["text"])
        self.assertEqual(self.cli("memory", "forget", entry["id"]).returncode, 0)
        self.assertEqual(json.loads(self.cli("memory", "search", "--kind", "clue").stdout), [])

    def test_note_alias_and_dream_requires_an_executor(self):
        note = self.cli("dream", "--note", "一次未解的导出差异")
        self.assertEqual(note.returncode, 0, note.stderr)
        self.assertEqual(json.loads(note.stdout)["kind"], "clue")
        result = self.cli("dream")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "failed")
        self.assertEqual(len(json.loads(self.cli("memory", "search", "--kind", "clue").stdout)), 1)
