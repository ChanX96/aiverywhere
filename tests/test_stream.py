import argparse
import asyncio
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import httpx

from aiverywhere.core.agent import Messages, Task
from aiverywhere.cli import invoke
from aiverywhere.core.store import Store


class StreamTest(unittest.TestCase):
    def test_messages_stream_delivers_text_deltas_once(self):
        events = [
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "你好"}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "，完成"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            {"type": "message_stop"},
        ]
        body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)

        async def reply(request):
            return httpx.Response(200, text=body,
                                  headers={"content-type": "text/event-stream"})

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            store = Store(root / "instance", project)
            store.initialize()
            client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
            provider = Messages(client, "test", settings={"model": "test",
                                                          "base_url": "http://test.invalid"})
            chunks = []

            async def run():
                task = Task(store)
                await task.run("只回复 OK", provider, on_text=chunks.append)
                return task

            task = asyncio.run(run())
            self.assertEqual(task.status, "completed")
            self.assertEqual(task.answer, "你好，完成")
            self.assertEqual("".join(chunks), "你好，完成")


    def test_messages_stream_drops_provider_thinking_blocks(self):
        events = [
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "thinking", "thinking": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "thinking_delta", "thinking": "内部推理"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "content_block_start", "index": 1,
             "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "text_delta", "text": "答复"}},
            {"type": "content_block_stop", "index": 1},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
        ]
        body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)

        async def reply(request):
            return httpx.Response(200, text=body,
                                  headers={"content-type": "text/event-stream"})

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            store = Store(root / "instance", project)
            store.initialize()
            client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
            provider = Messages(client, "test", settings={"model": "test",
                                                          "base_url": "http://test.invalid"})
            result = asyncio.run(provider.stream_send("system", [{"role": "user", "content": "hi"}], []))
            self.assertEqual(result["content"], [{"type": "text", "text": "答复"}])

    def test_cli_run_streams_text_once_without_duplicate_answer(self):
        events = [
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "streamed answer"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            {"type": "message_stop"},
        ]
        body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)

        async def reply(request):
            return httpx.Response(200, text=body,
                                  headers={"content-type": "text/event-stream"})

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            store = Store(root / "instance", project)
            store.initialize()
            (store.config_path).write_text(json.dumps({
                "model": {"model": "test", "base_url": "http://test.invalid"}}))
            args = argparse.Namespace(command="run", prompt="stream", task_id=None, model=None,
                                      json=False, allow_write=False, allow_exec=False,
                                      max_turns=3, timeout=5, host=None, mcp=[], agent_edit=None)
            client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
            output = io.StringIO()
            with patch("httpx.AsyncClient", return_value=client), redirect_stdout(output):
                result = asyncio.run(invoke(args, store))
            self.assertEqual(result, 0)
            self.assertEqual(output.getvalue().count("streamed answer"), 1)


if __name__ == "__main__":
    unittest.main()
