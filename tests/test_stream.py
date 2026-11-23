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

            thoughts = []

            async def run_with_thinking():
                task = Task(store)
                await task.run("只回复 OK", provider, on_text=chunks.append,
                               on_thinking=thoughts.append)
                return task

            task = asyncio.run(run_with_thinking())
            self.assertEqual(task.status, "completed")
            self.assertEqual(task.answer, "你好，完成")
            self.assertEqual("".join(chunks), "你好，完成")
            self.assertEqual(thoughts, [])
            self.assertEqual(task.thinking, "")


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
            thoughts = []
            result = asyncio.run(provider.stream_send(
                "system", [{"role": "user", "content": "hi"}], [], on_thinking=thoughts.append))
            self.assertEqual(result["content"], [{"type": "text", "text": "答复"}])
            self.assertEqual("".join(thoughts), "内部推理")

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


class WebChatStreamTest(unittest.TestCase):
    def test_web_state_exposes_text_and_thinking_while_running(self):
        import time

        from aiverywhere.integrations.web.chat import ChatSessions

        class Provider:
            async def agentloop(self, task, environment, messages, prompt, max_turns,
                                checkpoint, on_text=None, on_thinking=None, **kwargs):
                on_thinking("先分析，")
                on_thinking("再回答。")
                on_text("流式")
                await asyncio.sleep(0.2)
                on_text("回答")
                return "流式回答", messages

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            store = Store(root / "instance", project)
            store.initialize()
            sessions = ChatSessions(store)
            with patch("aiverywhere.integrations.web.chat.executor", return_value=Provider()):
                sessions.start("web-stream-12345678", "测试流式", False)
                for _ in range(100):
                    partial = sessions.state("web-stream-12345678")
                    if partial.get("thinking") and partial.get("stream_text"):
                        break
                    time.sleep(0.01)
                self.assertEqual(partial["status"], "running")
                self.assertEqual(partial["thinking"], "先分析，再回答。")
                self.assertEqual(partial["stream_text"], "流式")
                for _ in range(100):
                    state = sessions.state("web-stream-12345678")
                    if state["status"] != "running":
                        break
                    time.sleep(0.02)
            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["answer"], "流式回答")
            self.assertEqual(state["thinking"], "先分析，再回答。")
