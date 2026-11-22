import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from aiverywhere.core.agent import executor
from aiverywhere.core.configure import configure
from aiverywhere.core.protocols import ChatCompletions
from aiverywhere.core.store import Store


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = root / "project"
        self.project.mkdir()
        self.store = Store(root / "instance", self.project)

    def provider(self, reply, settings=None, handler=None):
        transport = httpx.MockTransport(handler or reply)
        client = httpx.AsyncClient(transport=transport)
        return ChatCompletions(client, None, settings=settings or {
            "protocol": "openai", "model": "test", "base_url": "http://test.invalid/v1",
            "api_key": "secret"})

    def test_openai_text_and_tool_call_translation(self):
        def reply(request):
            body = json.loads(request.content)
            self.assertEqual(body["model"], "test")
            self.assertEqual(body["messages"][0]["role"], "system")
            self.assertEqual(body["tools"][0]["function"]["name"], "read_file")
            return httpx.Response(200, json={"choices": [{
                "message": {"content": None, "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "read_file", "arguments": "{\"path\":\"x\"}"}}]},
                "finish_reason": "tool_calls"}]})

        provider = self.provider(reply)
        result = asyncio.run(provider.send("system", [{"role": "user", "content": "hi"}],
                                           [{"name": "read_file", "description": "read",
                                             "input_schema": {"type": "object", "properties": {}}}]))
        self.assertEqual(result["stop_reason"], "tool_use")
        self.assertEqual(result["content"][0]["input"], {"path": "x"})
        self.assertEqual(result["content"][0]["name"], "read_file")

    def test_openai_stream_text_and_tool_arguments(self):
        events = [
            {"choices": [{"delta": {"content": "hello"}, "finish_reason": None}]},
            {"choices": [{"delta": {"tool_calls": [{
                "index": 0, "id": "call_1", "function": {"name": "read_file", "arguments": "{\"path\":"}}]},
                "finish_reason": None}]},
            {"choices": [{"delta": {"tool_calls": [{
                "index": 0, "function": {"arguments": "\"x\"}"}}]}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        ]
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"

        def reply(request):
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

        provider = self.provider(reply)
        chunks = []
        result = asyncio.run(provider.stream_send(
            "system", [{"role": "user", "content": "hi"}], [], chunks.append))
        self.assertEqual("".join(chunks), "hello")
        self.assertEqual(result["stop_reason"], "tool_use")
        self.assertEqual(result["content"][0]["text"], "hello")
        self.assertEqual(result["content"][1]["input"], {"path": "x"})

    def test_ollama_default_and_custom_path_headers(self):
        ollama = ChatCompletions(httpx.AsyncClient(), "llama",
                                 settings={"protocol": "ollama", "model": "llama"})
        self.assertEqual(ollama.endpoint, "http://127.0.0.1:11434/v1/chat/completions")
        custom = ChatCompletions(httpx.AsyncClient(), "m", settings={
            "protocol": "custom", "model": "m", "base_url": "http://gateway.invalid",
            "chat_path": "/custom/chat", "headers": {"X-Provider": "local"}})
        self.assertEqual(custom.endpoint, "http://gateway.invalid/custom/chat")
        self.assertEqual(custom.headers["X-Provider"], "local")
        versioned = ChatCompletions(httpx.AsyncClient(), "m", settings={
            "protocol": "custom", "model": "m", "base_url": "http://gateway.invalid/v1",
            "chat_path": "/v1/chat/completions"})
        self.assertEqual(versioned.endpoint, "http://gateway.invalid/v1/chat/completions")

    def test_openai_tool_loop_round_trip(self):
        from aiverywhere.core.agent import Task

        calls = []

        def reply(request):
            body = json.loads(request.content)
            calls.append(body)
            if len(calls) == 1:
                return httpx.Response(200, json={"choices": [{
                    "message": {"content": None, "tool_calls": [{
                        "id": "call_1", "type": "function",
                        "function": {"name": "list_files", "arguments": "{\"path\":\".\"}"}}]},
                    "finish_reason": "tool_calls"}]})
            self.assertTrue(any(message.get("role") == "tool" for message in body["messages"]))
            return httpx.Response(200, json={"choices": [{
                "message": {"content": "tool loop done", "tool_calls": []},
                "finish_reason": "stop"}]})

        provider = self.provider(reply)
        task = Task(self.store)
        asyncio.run(task.run("list files", provider, max_turns=2, timeout=5))
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.answer, "tool loop done")
        self.assertEqual(len(calls), 2)

    def test_configure_and_executor_select_openai(self):
        self.store.initialize()
        configure(self.store, no_input=True, model="gpt-test", protocol="openai",
                  base_url="http://test.invalid/v1", api_key="secret")
        config = self.store.configuration()["model"]
        self.assertEqual(config["protocol"], "openai")
        self.assertEqual(config["base_url"], "http://test.invalid/v1")
        provider = executor(httpx.Client(), None, self.store)
        self.assertIsInstance(provider, ChatCompletions)
        self.assertEqual(provider.endpoint, "http://test.invalid/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
