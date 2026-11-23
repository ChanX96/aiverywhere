import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from aiverywhere.core import migrate, workflow
from aiverywhere.core.store import Store


class MigrationPackage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source_project = root / "source-project"
        self.source_project.mkdir()
        self.source = Store(root / "source-instance", self.source_project)
        self.source.initialize()
        self.source.remember("月报单位", "默认用万元。", "fact", "source-task")
        override = self.source.home / "overrides" / self.source.memory.key / "workflow" / "extract.md"
        override.parent.mkdir(parents=True)
        override.write_text("# extract\n契约版本 1\n")
        self.package = root / "my-agent.aiv.tar.gz"

    def test_export_inspect_import_preserves_memory_and_is_private(self):
        exported = migrate.export(self.source, self.package)
        self.assertEqual(exported["format"], migrate.FORMAT)
        info = migrate.inspect(self.package)
        self.assertEqual(info["skill_contract"], workflow.CONTRACT)
        self.assertIn("memory", info["kinds"])
        target_project = Path(self.temp.name) / "target-project"
        target_project.mkdir()
        target = Store(Path(self.temp.name) / "target-instance", target_project)
        target.initialize()
        result = migrate.import_package(target, self.package)
        shown = {item["title"]: item for _, item in target.memory.items()}
        self.assertIn("月报单位", shown)
        self.assertEqual(shown["月报单位"]["text"], "默认用万元。")
        self.assertEqual(result["memory"]["imported"], 1)
        with tarfile.open(self.package, "r:gz") as archive:
            names = set(archive.getnames())
        self.assertFalse(any(name.endswith("config.json") for name in names))
        self.assertFalse(any(name.endswith("events.jsonl") for name in names))

    def test_conflicts_are_not_overwritten(self):
        migrate.export(self.source, self.package)
        target_project = Path(self.temp.name) / "conflict-project"
        target_project.mkdir()
        target = Store(Path(self.temp.name) / "conflict-instance", target_project)
        target.initialize()
        source_id = self.source.memory.items()[0][1]["id"]
        target.remember("月报单位", "本地版本。", "fact", "local")
        # Copy the same stable ID so the package collides with the local record.
        local = target.memory.items()[0][1]
        local_path = target.memory.root / f"{source_id}.json"
        local_path.write_text(json.dumps(local | {"id": source_id}, ensure_ascii=False))
        (target.memory.root / f"{local['id']}.json").unlink()
        result = migrate.import_package(target, self.package)
        self.assertEqual(result["memory"]["imported"], 0)
        self.assertEqual(result["memory"]["conflicts"], 1)
        self.assertEqual(target.memory.items()[0][1]["text"], "本地版本。")

    def test_corrupt_and_traversal_packages_are_rejected(self):
        with tarfile.open(self.package, "w:gz") as archive:
            data = b'{"format":"bad","files":[]}'
            info = tarfile.TarInfo("manifest.json")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
            bad = tarfile.TarInfo("../escape")
            bad.size = 1
            archive.addfile(bad, io.BytesIO(b"x"))
        with self.assertRaises(migrate.MigrationError):
            migrate.inspect(self.package)
        with tarfile.open(self.package, "w:gz") as archive:
            data = b'{"format":"bad","files":[]}'
            info = tarfile.TarInfo("manifest.json")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        with self.assertRaises(migrate.MigrationError):
            migrate.inspect(self.package)


if __name__ == "__main__":
    unittest.main()
