import json
import tempfile
import unittest
from pathlib import Path

from aiverywhere.core.store import Store
from aiverywhere.integrations.bridges.registry import discover


class BridgeDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = root / "project"
        self.project.mkdir()
        self.store = Store(root / "instance", self.project)
        self.store.initialize()

    def write_bridge(self, ident, manifest):
        directory = self.project / "bridges" / ident
        directory.mkdir(parents=True)
        (directory / "bridge.json").write_text(json.dumps(manifest))

    def test_discovers_manifest_channel_and_does_not_execute(self):
        self.write_bridge("wechat", {
            "schema": 1, "id": "wechat", "name": "WeChat bridge",
            "channel": "wechat", "description": "local", "enabled": True,
            "command": ["/bin/echo", "must-not-run"],
            "health_url": "http://127.0.0.1:1/health"})
        self.store.config_path.write_text(json.dumps({"channels": {
            "wechat": {"url": "http://127.0.0.1:8787"}}}))
        rows = discover(self.store, check_health=True)
        self.assertEqual(rows[0]["id"], "wechat")
        self.assertTrue(rows[0]["channel_configured"])
        self.assertFalse(rows[0]["health"]["ok"])

    def test_invalid_manifests_are_ignored(self):
        self.write_bridge("bad", {"schema": 1, "id": "bad"})
        self.write_bridge("traversal", {
            "schema": 1, "id": "../escape", "name": "bad", "channel": "x"})
        (self.project / "bridges/not-a-dir").write_text("x")
        self.assertEqual(discover(self.store), [])
