import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from aiverywhere.core.store import Store


class ShellMemoryInterop(unittest.TestCase):
    def test_legacy_state_memory_migrates_to_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            store = Store(root / "instance", project)
            store.initialize()
            with store.edit() as state:
                state.setdefault("memory", {})["0123456789abcdef0123456789abcdef"] = {
                    "id": "0123456789abcdef0123456789abcdef", "kind": "fact",
                    "project": str(store.project), "revision": 3, "title": "旧记忆",
                    "text": "从 state.json 迁移。", "updated": 1, "source": "legacy", "shared": False}
            store.initialize()
            self.assertEqual(store.search("迁移", "fact", cold=True)[0]["revision"], 3)
            self.assertNotIn("memory", store.snapshot())
            self.assertTrue((store.home / "data/memory").is_dir())


    def test_shell_and_python_share_the_same_record(self):
        source = Path(__file__).resolve().parents[1]
        scripts = source / "skills/aiverywhere/scripts"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            home = project / ".aiverywhere"
            subprocess.run(["sh", str(scripts / "init-instance.sh"), str(project)],
                           check=True, capture_output=True, text=True)
            environment = {"AIVERYWHERE_HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
            created = subprocess.run(
                ["sh", str(scripts / "write-memory.sh"), "--kind", "fact",
                 "--title", "月报金额单位", "--text", "本项目月报金额统一使用万元。",
                 "--source", "host-a"], check=True, capture_output=True, text=True, env=environment)
            ident = json.loads(created.stdout)["id"]
            store = Store(home, project)
            self.assertEqual(store.search("月报", "fact")[0]["id"], ident)
            self.assertEqual(store.recall(ident)["text"], "本项目月报金额统一使用万元。")

            updated = store.remember("CLI 约定", "CLI 与宿主共用。", "fact", "cli")
            read = subprocess.run(
                ["sh", str(scripts / "read-memory.sh"), updated["id"]],
                check=True, capture_output=True, text=True, env=environment)
            self.assertEqual(json.loads(read.stdout)["source"], "cli")


if __name__ == "__main__":
    unittest.main()
