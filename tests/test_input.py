import asyncio
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from aiverywhere.core.agent import Task
from aiverywhere.core.store import Store
from aiverywhere.integrations.web.chat import ChatSessions


class RunningInputAndQuestions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        self.store = Store(Path(self.temp.name) / "instance", self.project)
        self.store.initialize()

    def test_task_question_is_resolved_by_provide(self):
        class Provider:
            async def agentloop(self, task, environment, messages, prompt, max_turns,
                                checkpoint, **kwargs):
                async def answer():
                    await asyncio.sleep(0.05)
                    task.provide("允许本次")
                asyncio.create_task(answer())
                answer_text = await task.ask_user("允许修改吗？", ["允许本次", "拒绝"])
                return "结果：" + answer_text, messages

        task = Task(self.store)
        asyncio.run(task.run("做一件事", Provider(), max_turns=2, timeout=5))
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.answer, "结果：允许本次")
        self.assertIsNone(task.pending_question)

    def test_task_inbox_is_bounded_and_drained(self):
        task = Task(self.store)
        self.assertEqual(task.provide("补充"), "inbox")
        self.assertEqual(task.drain_inbox(), ["补充"])
        self.assertEqual(task.drain_inbox(), [])
        with self.assertRaises(ValueError):
            task.provide("   ")

    def test_web_chat_accepts_running_input(self):
        class Provider:
            async def agentloop(self, task, environment, messages, prompt, max_turns,
                                checkpoint, **kwargs):
                async def answer():
                    await asyncio.sleep(0.1)
                    task.provide("决定")
                asyncio.create_task(answer())
                value = await task.ask_user("选择", ["决定"])
                return value, messages

        sessions = ChatSessions(self.store)
        with mock.patch("aiverywhere.integrations.web.chat.executor", return_value=Provider()):
            sessions.start("web-input-12345678", "测试", False)
            for _ in range(100):
                state = sessions.state("web-input-12345678")
                if state.get("question"):
                    break
                time.sleep(0.01)
            self.assertIsNotNone(state.get("question"))
            sessions.provide("web-input-12345678", "决定")
            for _ in range(100):
                state = sessions.state("web-input-12345678")
                if state.get("status") != "running":
                    break
                time.sleep(0.02)
            self.assertEqual(state.get("answer"), "决定")
            sessions.records["web-input-12345678"]["thread"].join(2)

