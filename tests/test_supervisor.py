import http.client
import json
import tempfile
import unittest
from pathlib import Path

from aiverywhere.core import supervisor
from aiverywhere.core.store import Store


class SupervisorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = root / "project"
        self.project.mkdir()
        self.store = Store(root / "instance", self.project)
        self.store.initialize()

    def tearDown(self):
        if getattr(self, "store", None) is not None:
            supervisor.stop(self.store)

    def health(self, info):
        connection = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=2)
        try:
            connection.request("GET", "/api/health",
                               headers={"Host": f"127.0.0.1:{info['port']}"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_channel_ingress_uses_daemon_token(self):
        self.store.config_path.write_text(json.dumps({"channels": {
            "test": {"url": "http://gateway.invalid"}}}))
        info = supervisor.ensure(self.store, port=0, open_browser="never")
        connection = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=2)
        body = json.dumps({"account": "a", "conversation": "c",
                           "message_id": "m", "text": "hello"})
        try:
            connection.request("POST", "/api/channels/test/messages", body=body,
                               headers={"Host": f"127.0.0.1:{info['port']}",
                                        "X-Aiverywhere-Token": info["token"],
                                        "Content-Type": "application/json"})
            response = connection.getresponse()
            payload = json.loads(response.read())
        finally:
            connection.close()
        self.assertEqual(response.status, 202)
        self.assertEqual(payload["channel"], "test")
        self.assertEqual(payload["status"], "queued")

    def test_start_status_idempotence_health_and_stop(self):
        info = supervisor.ensure(self.store, port=0, open_browser="never")
        self.assertGreater(info["port"], 0)
        self.assertEqual(self.health(info)[0], 200)
        status = supervisor.status(self.store)
        self.assertTrue(status["running"])
        self.assertEqual(status["pid"], info["pid"])

        again = supervisor.ensure(self.store, open_browser="never")
        self.assertEqual(again["pid"], info["pid"])

        result = supervisor.stop(self.store)
        self.assertTrue(result["stopped"])
        self.assertFalse(supervisor.status(self.store)["running"])
