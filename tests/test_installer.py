import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from aiverywhere.core import migrate
from aiverywhere.core.store import Store


class HostOnlyInstaller(unittest.TestCase):
    def test_host_only_install_defaults_to_project_instance(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            home = root / "home"
            project.mkdir()
            home.mkdir()
            environment = os.environ.copy()
            environment["HOME"] = str(home)
            result = subprocess.run(
                ["sh", str(source / "install.sh"), "--yes", "--no-cli", "--project", str(project)],
                capture_output=True, text=True, env=environment, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((project / ".aiverywhere/instance.json").is_file())
            self.assertTrue((project / ".aiverywhere/data/memory/default").is_dir())
            self.assertFalse((home / ".aiverywhere").exists())

    def test_reinstall_preserves_edited_skill_and_installs_workflow(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            instance = root / "instance"
            target = instance / "skills/aiverywhere"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("# user-edited\n")
            environment = os.environ.copy()
            environment["HOME"] = str(root / "home")
            result = subprocess.run(
                ["sh", str(source / "install.sh"), "--yes", "--no-cli",
                 "--project", str(project), "--home", str(instance)],
                capture_output=True, text=True, env=environment, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((target / "SKILL.md").read_text(), "# user-edited\n")
            self.assertTrue((target / "references/workflow/finish.md").is_file())
            self.assertIn("保留现有 SKILL.md", result.stdout)

    def test_host_only_import_uses_shell_without_python(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_project = root / "source-project"
            source_project.mkdir()
            source_store = Store(root / "source-instance", source_project)
            source_store.initialize()
            source_store.remember("迁移约定", "宿主导入可读。", "fact", "test")
            package = root / "agent.aiv.tar.gz"
            migrate.export(source_store, package)
            project = root / "target-project"
            project.mkdir()
            instance = root / "target-instance"
            environment = os.environ.copy()
            environment["HOME"] = str(root / "home")
            result = subprocess.run(
                ["sh", str(source / "install.sh"), "--yes", "--no-cli",
                 "--project", str(project), "--home", str(instance),
                 "--import", str(package)],
                capture_output=True, text=True, env=environment, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            listed = subprocess.run(
                ["sh", str(instance / "skills/aiverywhere/scripts/list-memory.sh"),
                 "--project", str(project), "--home", str(instance), "--kind", "fact"],
                capture_output=True, text=True, env=environment, timeout=10)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertIn("迁移约定", listed.stdout)

    def test_host_only_install_needs_no_python_environment(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            home = root / "home"
            home.mkdir()
            instance = root / "instance"
            environment = os.environ.copy()
            environment["HOME"] = str(home)
            result = subprocess.run(
                ["sh", str(source / "install.sh"), "--yes", "--no-cli",
                 "--project", str(project), "--home", str(instance)],
                capture_output=True, text=True, env=environment, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((instance / "instance.json").is_file())
            self.assertTrue((instance / "skills/aiverywhere/scripts/validate-memory.sh").is_file())
            self.assertTrue((project / ".agents/skills/aiverywhere").is_symlink())
            self.assertFalse((instance / "venv").exists())
            self.assertFalse((home / ".local/bin/aiverywhere").exists())


if __name__ == "__main__":
    unittest.main()
