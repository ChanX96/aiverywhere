import tempfile
import unittest
from pathlib import Path

from aiverywhere.core import adoption
from aiverywhere.core.store import Store


class HostAdoption(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = root / "monthly-report"
        self.project.mkdir()
        self.store = Store(root / "instance", self.project)
        self.store.initialize()

    def test_enable_is_idempotent_and_preserves_existing_rules(self):
        rules = self.project / "AGENTS.md"
        rules.write_text("# Team rules\n\nKeep this.\n")
        result = adoption.enable(self.store, "AGENTS.md")
        self.assertFalse(result["created"])
        text = rules.read_text()
        self.assertIn("# Team rules", text)
        self.assertEqual(text.count(adoption.BEGIN), 1)
        adoption.enable(self.store, "AGENTS.md")
        self.assertEqual(rules.read_text().count(adoption.BEGIN), 1)
        state = adoption.status(self.store)
        self.assertTrue(state["enabled"])
        self.assertEqual(state["state"], "enabled")

    def test_disable_removes_only_managed_block(self):
        rules = self.project / "CLAUDE.md"
        rules.write_text("# User instructions\n")
        adoption.enable(self.store, "CLAUDE.md", "claude-code")
        adoption.disable(self.store)
        text = rules.read_text()
        self.assertIn("# User instructions", text)
        self.assertNotIn(adoption.BEGIN, text)
        self.assertNotIn(adoption.END, text)

    def test_unsupported_file_and_unanswered_status(self):
        with self.assertRaises(adoption.AdoptionError):
            adoption.enable(self.store, "README.md")
        status = adoption.status(self.store)
        self.assertIn("supported", status)
        self.assertFalse(status["enabled"])
