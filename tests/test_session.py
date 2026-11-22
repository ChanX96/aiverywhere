import tempfile
import unittest
from pathlib import Path

from aiverywhere.core.context import ContextManager, ContextOverflow
from aiverywhere.core.session import SessionBusy, SessionStore
from aiverywhere.core.store import Store


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = root / "project"
        self.project.mkdir()
        self.store = Store(root / "instance", self.project)
        self.store.initialize()
        self.sessions = SessionStore(self.store)

    def test_persist_reload_latest_and_lock(self):
        session = self.sessions.create()
        turn_id = session.begin_turn("first")
        session.finish_turn(turn_id, [{"role": "user", "content": "first"},
                                      {"role": "assistant", "content": [{"type": "text", "text": "one"}]}],
                            "one")
        session.release()

        again = self.sessions.open(session.id)
        again.load()
        self.assertEqual(again.history()[0], {"role": "user", "content": "first"})
        self.assertEqual(again.turns()[0]["answer"], "one")
        self.assertEqual(self.sessions.latest().id, session.id)

        held = self.sessions.open(session.id)
        held.acquire()
        with self.assertRaises(SessionBusy):
            self.sessions.open(session.id).acquire()
        held.release()
        self.sessions.open(session.id).release()

    def test_partial_tail_is_ignored_and_repaired(self):
        session = self.sessions.create()
        turn_id = session.begin_turn("first")
        session.finish_turn(turn_id, [{"role": "user", "content": "first"}], "one")
        session.release()
        with session.path.open("ab") as stream:
            stream.write(b'{"seq":3,"type":"turn"')

        loaded = self.sessions.open(session.id)
        loaded.load()
        self.assertTrue(loaded.recovered)
        self.assertEqual(loaded.history(), [{"role": "user", "content": "first"}])
        loaded.acquire()
        try:
            turn = loaded.begin_turn("second")
            loaded.finish_turn(turn, [{"role": "user", "content": "second"}], "two")
        finally:
            loaded.release()

        check = self.sessions.open(session.id)
        check.load()
        self.assertEqual([m["content"] for m in check.history()], ["first", "second"])
        self.assertFalse(check.recovered)

    def test_interrupted_turn_is_marked_unknown(self):
        session = self.sessions.create()
        session.begin_turn("unfinished")
        session.release()
        loaded = self.sessions.open(session.id)
        loaded.load()
        self.assertTrue(loaded.pending)
        loaded.acquire()
        try:
            self.assertTrue(loaded.resolve_pending())
        finally:
            loaded.release()
        check = self.sessions.open(session.id)
        check.load()
        self.assertFalse(check.pending)
        self.assertEqual(check.turns(), [])
        self.assertEqual(check.events[-1]["status"], "result_unknown")


class ContextTest(unittest.TestCase):
    class Provider:
        def __init__(self, fail=False):
            self.fail = fail
            self.calls = 0

        async def send(self, system, messages, tools):
            self.calls += 1
            if self.fail:
                raise RuntimeError("summary failed")
            return {"content": [{"type": "text", "text": "summary: retain decisions and paths"}]}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        project = root / "project"
        project.mkdir()
        self.store = Store(root / "instance", project)
        self.store.initialize()

    @staticmethod
    def messages(count=12):
        result = []
        for index in range(count):
            result.append({"role": "user", "content": f"question {index} " + "x" * 300})
            result.append({"role": "assistant", "content": [{"type": "text", "text": "answer " + "y" * 300}]})
        return result

    def test_auto_compaction_keeps_recent_and_persists_summary_callback(self):
        summaries = []
        provider = self.Provider()
        manager = ContextManager(self.store, provider,
                                 settings={"max_context_tokens": 1000, "compact_at": 0.5,
                                           "keep_recent_turns": 2, "summary_max_chars": 1000},
                                 on_summary=lambda text, method, covers: summaries.append((text, method, covers)))
        view = __import__("asyncio").run(manager.view("system", self.messages(), []))
        self.assertEqual(provider.calls, 1)
        self.assertTrue(view[0]["content"].startswith("[Earlier conversation summary]"))
        self.assertEqual(summaries[0][1], "model")
        self.assertGreater(summaries[0][2], 0)

    def test_summary_failure_uses_deterministic_fallback(self):
        summaries = []
        manager = ContextManager(self.store, self.Provider(fail=True),
                                 settings={"max_context_tokens": 1000, "compact_at": 0.5,
                                           "keep_recent_turns": 2, "summary_max_chars": 1000},
                                 on_summary=lambda text, method, covers: summaries.append((text, method, covers)))
        view = __import__("asyncio").run(manager.view("system", self.messages(), []))
        self.assertEqual(summaries[0][1], "deterministic")
        self.assertIn("Earlier", view[0]["content"] + "Earlier")

    def test_task_uses_compaction_view_and_counts_it(self):
        from aiverywhere.core.agent import Task

        class Provider:
            def __init__(self):
                self.view = None
                self.summaries = 0

            async def send(self, system, messages, tools):
                self.summaries += 1
                return {"content": [{"type": "text", "text": "summary"}]}

            async def agentloop(self, task, environment, messages, prompt, max_turns,
                                checkpoint, context_manager=None):
                self.view = await context_manager.view("system", messages, [])
                return "answer", [*messages, {"role": "assistant", "content": "answer"}]

        provider = Provider()
        manager = ContextManager(self.store, provider,
                                 settings={"max_context_tokens": 1000, "compact_at": 0.5,
                                           "keep_recent_turns": 2, "summary_max_chars": 1000})
        task = Task(self.store)
        task.history = self.messages()
        __import__("asyncio").run(task.run("next", provider, max_turns=1, timeout=5,
                                           context_manager=manager))
        self.assertEqual(task.status, "completed")
        self.assertGreaterEqual(manager.compactions, 1)
        self.assertTrue(provider.view[0]["content"].startswith("[Earlier conversation summary]"))
        self.assertGreaterEqual(provider.summaries, 1)

    def test_single_oversized_turn_fails_instead_of_silent_loss(self):
        manager = ContextManager(self.store, self.Provider(),
                                 settings={"max_context_tokens": 1000, "compact_at": 0.5,
                                           "keep_recent_turns": 2})
        with self.assertRaises(ContextOverflow):
            __import__("asyncio").run(manager.view("system", [{"role": "user", "content": "x" * 20000}], []))
