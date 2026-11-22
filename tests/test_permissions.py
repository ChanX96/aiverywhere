import argparse
import asyncio
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from aiverywhere.cli import invoke
from aiverywhere.cli.main import parser
from aiverywhere.core.agent import Task
from aiverywhere.core.session import SessionStore
from aiverywhere.core.store import Store


class PermissionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = root / "project"
        self.project.mkdir()
        self.store = Store(root / "instance", self.project)
        self.store.initialize()

    def args(self, **changes):
        base = dict(command="chat", json=True, allow_write=False, allow_exec=False,
                    max_turns=2, model=None, timeout=5, host=None, mcp=[],
                    agent_edit=None, new_session=False, ask_permissions=False,
                    no_network=False)
        base.update(changes)
        return argparse.Namespace(**base)

    def test_network_permission_filters_web_tools(self):
        task = Task(self.store, network_allowed=False)
        self.assertNotIn("web_search", task.tools.available)
        self.assertNotIn("web_fetch", task.tools.available)
        self.assertIn("web_search", Task(self.store).tools.available)

    def test_grant_is_audited_in_session(self):
        async def lines():
            yield "/grant write"
            yield "/permissions"
            yield "/quit"

        out = io.StringIO()
        with patch("aiverywhere.cli.main.input_lines", lines), redirect_stdout(out):
            asyncio.run(invoke(self.args(), self.store))
        self.assertIn("write: allowed", out.getvalue())
        session = SessionStore(self.store).latest()
        self.assertIsNotNone(session)
        session.load()
        permissions = [e for e in session.events if e.get("type") == "permission"]
        self.assertEqual(permissions[-1]["capability"], "write")
        self.assertTrue(permissions[-1]["allowed"])
        session.release()

    def test_ask_permissions_waits_for_approve(self):
        class Provider:
            async def agentloop(self, task, environment, messages, prompt, max_turns,
                                checkpoint, context_manager=None):
                allowed = await task.approval("write_file", {"path": "x", "text": "y",
                                                             "expected": "new"})
                answer = "approved" if allowed else "denied"
                return answer, [*messages, {"role": "assistant", "content": answer}]

        async def lines():
            yield "write something"
            yield "/approve"
            yield "/permissions"
            yield "/quit"

        out = io.StringIO()
        with patch("aiverywhere.cli.main.input_lines", lines), \
                patch("aiverywhere.cli.main.executor", return_value=Provider()), \
                redirect_stdout(out):
            asyncio.run(invoke(self.args(ask_permissions=True), self.store))
        events = [json.loads(line) for line in out.getvalue().splitlines()]
        results = [event for event in events if event.get("event") == "result"]
        self.assertEqual(results[0]["answer"], "approved")
        self.assertIn("write: allowed (ask each time)", out.getvalue())

    def test_root_flags_parse(self):
        args = parser().parse_args(["--ask-permissions", "--no-network"])
        self.assertTrue(args.root_ask_permissions)
        self.assertTrue(args.root_no_network)


class PromptLoopTest(unittest.TestCase):
    def test_tty_prompt_returns_after_each_task(self):
        from aiverywhere.cli.main import chat
        from unittest.mock import patch

        class Provider:
            async def agentloop(self, task, environment, messages, prompt, max_turns,
                                checkpoint, context_manager=None):
                return "answer", [*messages, {"role": "assistant", "content": "answer"}]

        class Prompt:
            def __init__(self):
                self.lines = ["hello", "/quit"]
                self.calls = 0

            async def prompt_async(self, text):
                self.calls += 1
                if not self.lines:
                    raise EOFError
                return self.lines.pop(0)

        args = argparse.Namespace(allow_write=False, allow_exec=False, ask_permissions=False,
                                  no_network=False, host=None, mcp=[], agent_edit=None,
                                  max_turns=2, timeout=5, json=False, new_session=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            store = Store(root / "instance", project)
            store.initialize()
            prompt = Prompt()
            with patch("aiverywhere.cli.main._make_prompt_session", return_value=prompt), \
                    patch("aiverywhere.cli.main.sys.stdin.isatty", return_value=True), \
                    patch("aiverywhere.cli.main.sys.stdout.isatty", return_value=False), \
                    patch("builtins.print"):
                asyncio.run(chat(args, store, Provider()))
            self.assertEqual(prompt.calls, 2)
