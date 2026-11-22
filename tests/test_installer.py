import os
import subprocess
import tempfile
import unittest
from pathlib import Path


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
