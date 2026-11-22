import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from aiverywhere.core import channels
from aiverywhere.core.store import Store


class ChannelTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = root / "project"
        self.project.mkdir()
        self.store = Store(root / "instance", self.project)
        self.store.initialize()
        self.store.config_path.write_text(json.dumps({"channels": {
            "feishu": {"url": "https://feishu.invalid"},
            "wechat": {"url": "https://wechat.invalid", "auth_token": "token"}}}))

    def test_routes_each_message_to_its_originating_channel(self):
        message = {"account": "a", "conversation": "c", "message_id": "m1", "text": "hello"}
        feishu = channels.receive(self.store, message, "feishu")
        wechat = channels.receive(self.store, message | {"message_id": "m2"}, "wechat")
        self.assertEqual(feishu["channel"], "feishu")
        self.assertEqual(wechat["channel"], "wechat")
        self.assertNotEqual(feishu["task_id"], wechat["task_id"])
        self.assertEqual(channels.status(self.store, feishu["task_id"])["channel"], "feishu")
        with self.assertRaises(PermissionError):
            channels.receive(self.store, message, "missing")

    def test_reply_uses_the_same_channel_and_envelope(self):
        class Provider:
            async def agentloop(self, task, environment, messages, prompt, max_turns,
                                checkpoint, context_manager=None):
                return "reply", [*messages, {"role": "assistant", "content": "reply"}]

        sent = []

        def gateway(request):
            body = json.loads(request.content)
            sent.append((str(request.url), body, request.headers.get("Authorization")))
            return httpx.Response(200, json={
                "channel": body["channel"], "account": body["account"],
                "conversation": body["conversation"], "reply_to": body["reply_to"],
                "state": "accepted", "receipt": "r-1"})

        key = channels.receive(self.store, {
            "account": "a", "conversation": "c", "message_id": "m", "text": "hello"},
            "wechat")["task_id"]

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as client:
                with patch("aiverywhere.core.channels.executor", return_value=Provider()):
                    first = await channels.process(self.store, client, key)
                    second = await channels.process(self.store, client, key)
                return first, second

        first, second = asyncio.run(run())
        self.assertEqual(first["channel"], "wechat")
        self.assertEqual(second["delivery"], "accepted")
        self.assertEqual(sent[0][0], "https://wechat.invalid/messages")
        self.assertEqual(sent[0][1]["channel"], "wechat")
        self.assertEqual(sent[0][1]["account"], "a")
        self.assertEqual(sent[0][1]["conversation"], "c")
        self.assertEqual(sent[0][2], "Bearer token")

    def test_legacy_wechat_config_maps_to_a_webhook_channel(self):
        self.store.config_path.write_text(json.dumps({"wechat": {
            "project": str(self.project), "url": "https://wechat.invalid",
            "account": "a", "conversation": "c"}}))
        config = channels.configs(self.store)["wechat"]
        self.assertEqual(config["type"], "webhook")
        self.assertEqual(config["account"], "a")
        self.store.config_path.write_text(json.dumps({"channels": {}}))
        self.assertEqual(channels.configs(self.store), {})
