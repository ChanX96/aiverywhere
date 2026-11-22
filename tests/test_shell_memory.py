import json
import shutil
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


    def test_legacy_migration_keeps_other_projects_and_is_resumable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_a = root / "a"
            project_b = root / "b"
            project_a.mkdir()
            project_b.mkdir()
            home = root / "shared-instance"
            first = Store(home, project_a)
            second = Store(home, project_b)
            first.initialize()
            ids = {
                "a": "0123456789abcdef0123456789abcdef",
                "b": "1123456789abcdef0123456789abcdef",
            }
            with first.edit() as state:
                state["memory"] = {
                    ids["a"]: {"id": ids["a"], "kind": "fact", "project": str(project_a),
                               "revision": 1, "title": "A 记忆", "text": "只属于 A。",
                               "updated": 1, "source": "legacy", "shared": False},
                    ids["b"]: {"id": ids["b"], "kind": "fact", "project": str(project_b),
                               "revision": 1, "title": "B 记忆", "text": "只属于 B。",
                               "updated": 1, "source": "legacy", "shared": False},
                }
            first.initialize()
            self.assertEqual(first.search("A", "fact", cold=True)[0]["id"], ids["a"])
            self.assertEqual(set(first.snapshot()["memory"]), {ids["b"]})
            second.initialize()
            self.assertEqual(second.search("B", "fact", cold=True)[0]["id"], ids["b"])
            self.assertEqual(first.search("A", "fact", cold=True)[0]["id"], ids["a"])
            self.assertNotIn("memory", first.snapshot())

    def test_existing_target_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            store = Store(root / "instance", project)
            store.initialize()
            ident = "2123456789abcdef0123456789abcdef"
            record = {"schema_version": 1, "id": ident, "revision": 1, "kind": "fact",
                      "title": "已存在", "text": "目标内容。", "source": "new",
                      "updated": "2026-11-22T10:00:00Z", "shared": False}
            store.memory.write_record(record)
            with store.edit() as state:
                state["memory"] = {ident: {"id": ident, "kind": "fact", "project": str(project),
                                           "revision": 1, "title": "已存在", "text": "不同内容。",
                                           "updated": 1, "source": "legacy", "shared": False}}
            store.initialize()
            self.assertEqual(store.memory.record(ident)["text"], "目标内容。")
            self.assertEqual(set(store.snapshot()["memory"]), {ident})

    def test_shared_instance_isolates_each_project(self):
        source = Path(__file__).resolve().parents[1]
        scripts = source / "skills/aiverywhere/scripts"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_a = root / "a"
            project_b = root / "b"
            project_a.mkdir()
            project_b.mkdir()
            home = root / "shared"
            environment = {"AIVERYWHERE_HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
            for project in (project_a, project_b):
                subprocess.run(["sh", str(scripts / "init-instance.sh"), str(project)],
                               check=True, capture_output=True, text=True, env=environment)
            created = {}
            for name, project in (("a", project_a), ("b", project_b)):
                result = subprocess.run(
                    ["sh", str(scripts / "write-memory.sh"), "--project", str(project),
                     "--home", str(home), "--kind", "fact", "--title", "同名事实",
                     "--text", f"项目 {name} 的内容", "--source", "host"],
                    check=True, capture_output=True, text=True, env=environment)
                created[name] = json.loads(result.stdout)["id"]
            store_a = Store(home, project_a)
            store_b = Store(home, project_b)
            self.assertNotEqual(store_a.memory.key, store_b.memory.key)
            self.assertEqual(store_a.recall(created["a"])["text"], "项目 a 的内容")
            self.assertEqual(store_b.recall(created["b"])["text"], "项目 b 的内容")
            with self.assertRaises(ValueError):
                store_a.recall(created["b"])

    def test_shared_instance_without_jq_still_initializes(self):
        source = Path(__file__).resolve().parents[1]
        scripts = source / "skills/aiverywhere/scripts"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            # A PATH without jq still needs the POSIX tools used by init.
            bindir = root / "bin"
            bindir.mkdir()
            for name in ("sh", "sed", "awk", "mkdir", "chmod", "mv", "ln", "find", "readlink",
                         "dirname", "basename", "wc", "tr", "pwd", "cat", "sha256sum", "shasum", "openssl"):
                target = shutil.which(name)
                if target:
                    (bindir / name).symlink_to(target)
            environment = {"PATH": str(bindir)}
            result = subprocess.run(
                ["sh", str(scripts / "init-instance.sh"), str(project)],
                check=True, capture_output=True, text=True, env=environment)
            self.assertEqual(json.loads(result.stdout)["status"], "ok")
            self.assertTrue((project / ".aiverywhere/instance.json").is_file())

    def test_retry_after_target_write_preserves_identical_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            store = Store(root / "instance", project)
            store.initialize()
            ident = "3123456789abcdef0123456789abcdef"
            record = {"schema_version": 1, "id": ident, "revision": 1, "kind": "fact",
                      "title": "已完成写入", "text": "迁移目标。", "source": "legacy",
                      "updated": "2026-11-22T10:00:00Z", "shared": False}
            store.memory.write_record(record)
            with store.edit() as state:
                state["memory"] = {ident: {"id": ident, "kind": "fact", "project": str(project),
                                           "revision": 1, "title": "已完成写入", "text": "迁移目标。",
                                           "updated": "2026-11-22T10:00:00Z", "source": "legacy", "shared": False}}
            store.initialize()
            self.assertEqual(store.memory.record(ident)["text"], "迁移目标。")
            self.assertNotIn("memory", store.snapshot())

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
                ["sh", str(scripts / "write-memory.sh"), "--project", str(project),
                 "--kind", "fact", "--title", "月报金额单位",
                 "--text", "本项目月报金额统一使用万元。", "--source", "host-a"], check=True, capture_output=True, text=True, env=environment)
            ident = json.loads(created.stdout)["id"]
            store = Store(home, project)
            self.assertEqual(store.search("月报", "fact")[0]["id"], ident)
            self.assertEqual(store.recall(ident)["text"], "本项目月报金额统一使用万元。")

            updated = store.remember("CLI 约定", "CLI 与宿主共用。", "fact", "cli")
            read = subprocess.run(
                ["sh", str(scripts / "read-memory.sh"), updated["id"], "--project", str(project)],
                check=True, capture_output=True, text=True, env=environment)
            self.assertEqual(json.loads(read.stdout)["source"], "cli")


if __name__ == "__main__":
    unittest.main()
