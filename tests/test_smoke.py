import argparse
import asyncio
import io
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import httpx

from aiverywhere.core.agent import Messages, Task
from aiverywhere.cli import invoke
from aiverywhere.core.store import Store
from aiverywhere.core.session import SessionStore
from aiverywhere.integrations import wechat
from aiverywhere.integrations.web.server import create_server


class Smoke(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = Store(self.root / "install", self.project)

    def cli(self, *args):
        return subprocess.check_output(
            [sys.executable, "-m", "aiverywhere", "--home", str(self.store.home), *args],
            cwd=self.project, text=True)

    def test_host_resource_and_cross_process_recall(self):
        self.assertIn("name: aiverywhere", self.cli("skill"))
        (self.project / "pyproject.toml").touch()
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "", "CLAUDECODE": ""}):
            local = json.loads(self.cli("env"))
        self.assertEqual(local["execution"], "local_process")
        self.assertEqual(local["host"]["source"], "unknown")
        self.assertEqual(local["system"], platform.system())
        self.assertEqual(local["project_root"], str(self.project.resolve()))
        self.assertIn("pyproject.toml", local["project_markers"])
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "private-id", "CLAUDECODE": ""}):
            hinted = self.cli("env")
            declared = json.loads(self.cli("--host", "smoke-host", "env"))
        with patch.dict(os.environ, {"AIVERYWHERE_HOST": "any-host", "CODEX_THREAD_ID": "", "CLAUDECODE": ""}):
            from_environment = json.loads(self.cli("env"))
        self.assertNotIn("private-id", hinted)
        self.assertEqual(json.loads(hinted)["host"], {"name": "codex", "source": "hint"})
        self.assertEqual(declared["host"], {"name": "smoke-host", "source": "declared"})
        self.assertEqual(from_environment["host"], {"name": "any-host", "source": "environment"})
        self.assertFalse(declared["grants"]["project_write"])
        self.assertIn("unattended_wakeup", declared["unverified"])
        self.assertFalse(self.store.data.exists())
        item = json.loads(self.cli("memory", "put", "月报", "在副本上编辑"))
        matches = json.loads(self.cli("memory", "search", "月报"))
        self.assertEqual(matches[0]["id"], item["id"])
        self.assertEqual(json.loads(self.cli("memory", "get", item["id"]))["text"], "在副本上编辑")
        self.assertEqual(json.loads(self.cli("--project", str(self.root), "memory", "search", "月报")), [])

    def test_init_adopts_existing_instance_and_keeps_all_files_local(self):
        old = self.store.home / ".project" / "SKILL.md"
        old.parent.mkdir(parents=True)
        source = self.cli("skill") + "\n已有的实例约定。\n"
        old.write_text(source)
        self.store.data.mkdir()
        (self.store.data / "model.json").write_text('{"model":"original"}')
        (self.store.data / "mcp.json").write_text('{"mcpServers":{}}')
        info = json.loads(self.cli("init"))
        self.assertEqual(Path(info["agent"]["path"]), self.store.agent_file)
        self.assertEqual(self.store.agent_file.read_text(), source)
        cfg = Path(info["config"])
        self.assertEqual(json.loads(cfg.read_text()),
                         {"model": {"model": "original"}, "defaults": {}, "mcpServers": {}, "wechat": {}, "session": {}, "channels": {}})
        cfg.write_text('{"model":{"model":"updated"}}')
        self.cli("init")
        self.assertEqual(self.store.configuration()["model"]["model"], "updated")
        self.assertEqual(list(self.project.iterdir()), [])
        (self.store.data / "memory").symlink_to(self.project / "outside")
        with self.assertRaises(PermissionError):
            self.store.remember("边界", "留在项目", "fact", "user")
        self.assertFalse((self.project / "outside").exists())

    def test_messages_tool_round_trip(self):
        (self.project / "README.md").write_text("用 unittest 验证。")
        memory = self.store.remember("验证", "先读 README", "fact", "user")

        def reply(request):
            body = json.loads(request.content)
            self.assertEqual(request.url.path, "/v1/messages")
            turns = body["messages"]
            if len(turns) == 1:
                context = json.loads(body["system"].splitlines()[-1])
                self.assertEqual(context["project_root"], str(self.project.resolve()))
                self.assertEqual(context["entry"], "delegate")
                self.assertEqual(context["grants"]["project_write"], True)
                self.assertTrue({"read_file", "list_files", "recall", "discover"} <= {t["name"] for t in body["tools"]})
                # Publish from another writer while the first request is in flight.
                self.store.revise_agent(context["agent_revision"], self.store.agent_file.read_text() + "\n本轮核对文件修订。\n")
                calls = [("read", "read_file", {"path": "README.md"}), ("recall", "recall", {"id": memory["id"]})]
            elif len(turns) == 3:
                self.assertIn("本轮核对文件修订。", body["system"])
                self.assertEqual(json.loads(body["system"].splitlines()[-1])["agent_revision"], self.store.skill_info()["revision"])
                results = turns[-1]["content"]
                self.assertEqual([r["tool_use_id"] for r in results], ["read", "recall"])
                self.assertIn("unittest", json.loads(results[0]["content"])["text"])
                self.store.remember("验证", "新正文按需取回", "fact", "user", revision=memory["revision"])
                calls = [("ls", "list_files", {})]
            else:
                context = json.loads(body["system"].splitlines()[-1])
                self.assertEqual(context["changed_memory"], {memory["id"]: memory["revision"] + 1})
                self.assertNotIn("新正文按需取回", body["system"])
                return httpx.Response(200, json={"stop_reason": "end_turn", "content": [
                    {"type": "text", "text": "用 unittest。依据 README.md。"}]})
            blocks = [{"type": "tool_use", "id": i, "name": n, "input": a} for i, n, a in calls]
            return httpx.Response(200, json={"stop_reason": "tool_use", "content": blocks})

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
                task = Task(self.store, writable=True, entry="delegate", host="smoke-host")
                await task.agentloop("怎样验证？", Messages(client, "smoke"))
                self.assertEqual(task.status, "completed", task.error)
                self.assertIn("README.md", task.answer)
                self.assertTrue(all(r["ok"] for r in task.receipts))

        with patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "http://test.invalid"}):
            asyncio.run(run())

    def test_native_cli_uses_one_skill_and_returns_the_hosts_final_text(self):
        info = json.loads(self.cli("skill", "--info"))
        original = Path(info["path"]).read_text()
        revised = original + "\n本实例的合计需注明单位。\n"
        revision = self.store.revise_agent(info["revision"], revised)["revision"]
        with self.assertRaises(ValueError):
            self.store.revise_agent(info["revision"], original)
        (self.project / "amount").write_text("42")
        runner = self.root / "host.py"
        runner.write_text(
            "import json, os, sys\nfrom pathlib import Path\n"
            "request = json.load(sys.stdin)\n"
            "assert not os.getenv('AIVERYWHERE_PRIVATE_SMOKE')\n"
            "assert '本实例的合计需注明单位' in request['instructions']\n"
            "assert request['messages'][-1]['content'] == '读取合计'\n"
            "with Path('calls').open('a') as f: f.write('1')\n"
            "print(Path('amount').read_text() + ' 元')\n")
        (self.store.config_path).write_text(json.dumps({"model": {
            "project": str(self.store.project), "command": [sys.executable, str(runner)]}}))
        with patch.dict(os.environ, {"AIVERYWHERE_PRIVATE_SMOKE": "只属父进程"}):
            for _ in range(2):
                result = json.loads(self.cli("run", "--json", "--task-id", "native-1", "读取合计"))
                self.assertEqual((result["executor"], result["answer"], result["agent_revision"]), ("native", "42 元", revision))
        self.assertEqual((self.project / "calls").read_text(), "1")
        self.assertEqual(self.cli("skill"), revised)

    def test_idle_dream_and_missed_schedule(self):
        self.assertEqual(json.loads(self.cli("dream")), {"status": "idle", "model_calls": 0})
        self.cli("schedule", "add", "已错过的周报", "--at", "2020-01-01T09:00:00+08:00")
        self.assertEqual(self.cli("wake"), "")
        notice, = json.loads(self.cli("schedule", "notices"))
        self.assertEqual((notice["status"], notice["count"]), ("missed", 1))
        self.assertEqual(self.cli("schedule", "notices"), "")
        self.assertEqual(json.loads(self.cli("schedule", "results")), [])

    def test_chat_runs_lines_sequentially(self):
        async def run():
            out = io.StringIO()

            async def reply(request):
                body = json.loads(request.content)
                prompt = body["messages"][-1]["content"]
                return httpx.Response(200, json={"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "done:" + prompt}]})

            async def lines():
                # Feed a piped line after each turn; older runtimes otherwise
                # race /quit ahead of the second queued task.
                yield "first"
                await asyncio.sleep(0.05)
                yield "second"
                await asyncio.sleep(0.05)
                yield "/quit"

            self.store.initialize()
            (self.store.config_path).write_text(
                '{"model":{"model":"test","base_url":"http://test.invalid"}}')
            client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
            args = argparse.Namespace(command="chat", json=True, allow_write=False, allow_exec=False, max_turns=3,
                                      model=None, timeout=5, host=None, mcp=[], agent_edit=None)
            with patch("httpx.AsyncClient", return_value=client), patch("aiverywhere.cli.main.input_lines", lines), \
                    redirect_stdout(out):
                await asyncio.wait_for(invoke(args, self.store), 3)
            events = [json.loads(line) for line in out.getvalue().splitlines()]
            self.assertEqual([e["answer"] for e in events if e["event"] == "result"],
                             ["done:first", "done:second"])
            results = [e for e in events if e["event"] == "result"]
            self.assertEqual(len({e["task_id"] for e in results}), 1)
            events = [e for e in events if e["event"] != "help"]
            self.assertEqual([e["event"] for e in events],
                             ["accepted", "start", "result", "accepted", "start", "result"])

        asyncio.run(run())

    def test_chat_cancel_stops_current_task_and_keeps_prompt(self):
        class Slow:
            async def agentloop(self, task, environment, messages, prompt, max_turns, checkpoint, **kwargs):
                await asyncio.sleep(10)
                return "should not arrive", messages

        async def run():
            out = io.StringIO()

            async def lines():
                yield "slow task"
                yield "/cancel"
                yield "/quit"

            self.store.initialize()
            args = argparse.Namespace(command="chat", json=True, allow_write=False, allow_exec=False,
                                      max_turns=3, model=None, timeout=30, host=None, mcp=[], agent_edit=None)
            with patch("aiverywhere.cli.main.executor", return_value=Slow()), \
                    patch("aiverywhere.cli.main.input_lines", lines), redirect_stdout(out):
                await asyncio.wait_for(invoke(args, self.store), 3)
            events = [json.loads(line) for line in out.getvalue().splitlines()]
            results = [event for event in events if event["event"] == "result"]
            self.assertEqual(results[0]["status"], "cancelled")
            self.assertEqual(results[0]["answer"], "")

        asyncio.run(run())

    def test_chat_resumes_latest_session_after_process_restart(self):
        async def run():
            requests = []

            async def reply(request):
                body = json.loads(request.content)
                requests.append(body)
                return httpx.Response(200, json={"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "done:" + body["messages"][-1]["content"]}]})

            self.store.initialize()
            (self.store.config_path).write_text(
                '{"model":{"model":"test","base_url":"http://test.invalid"}}')

            def args():
                return argparse.Namespace(command="chat", json=True, allow_write=False,
                                          allow_exec=False, max_turns=3, model=None,
                                          timeout=5, host=None, mcp=[], agent_edit=None,
                                          new_session=False)

            async def lines(values):
                for value in values:
                    yield value

            client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
            with patch("httpx.AsyncClient", return_value=client),                     patch("aiverywhere.cli.main.input_lines", lambda: lines(["first", "/quit"])),                     redirect_stdout(io.StringIO()):
                await asyncio.wait_for(invoke(args(), self.store), 3)
            sessions = SessionStore(self.store)
            first = sessions.latest()
            self.assertIsNotNone(first)
            first_id = first.id
            first.release()

            client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
            with patch("httpx.AsyncClient", return_value=client),                     patch("aiverywhere.cli.main.input_lines", lambda: lines(["second", "/quit"])),                     redirect_stdout(io.StringIO()):
                await asyncio.wait_for(invoke(args(), self.store), 3)
            second = SessionStore(self.store).latest()
            self.assertEqual(second.id, first_id)
            second.release()
            self.assertEqual([m["content"] for m in second.history()],
                             ["first", [{"type": "text", "text": "done:first"}],
                              "second", [{"type": "text", "text": "done:second"}]])
            self.assertIn("first", json.dumps(requests[1]["messages"], ensure_ascii=False))

        asyncio.run(run())

    def test_new_command_starts_a_second_session(self):
        async def run():
            async def reply(request):
                body = json.loads(request.content)
                return httpx.Response(200, json={"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "done:" + body["messages"][-1]["content"]}]})

            self.store.initialize()
            (self.store.config_path).write_text(
                '{"model":{"model":"test","base_url":"http://test.invalid"}}')

            async def lines():
                for value in ("one", "/new", "two", "/quit"):
                    yield value

            args = argparse.Namespace(command="chat", json=True, allow_write=False,
                                      allow_exec=False, max_turns=3, model=None,
                                      timeout=5, host=None, mcp=[], agent_edit=None,
                                      new_session=False)
            client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
            with patch("httpx.AsyncClient", return_value=client),                     patch("aiverywhere.cli.main.input_lines", lines), redirect_stdout(io.StringIO()):
                await asyncio.wait_for(invoke(args, self.store), 3)
            rows = SessionStore(self.store).list()
            self.assertEqual(len(rows), 2)
            self.assertEqual(len({row["id"] for row in rows}), 2)

        asyncio.run(run())

    def test_wake_runs_one_due_plan_and_exits(self):
        async def run():
            out = io.StringIO()

            async def reply(request):
                return httpx.Response(200, json={"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "scheduled done"}]})

            self.store.initialize()
            (self.store.config_path).write_text(
                '{"model":{"model":"test","base_url":"http://test.invalid"}}')
            args = argparse.Namespace(
                at=datetime.now().astimezone().isoformat(), timezone=None, repeat="once",
                grace=3600, prompt="run once", model=None, allow_write=False, mcp=[])
            from aiverywhere.core import background
            plan = background.add_plan(self.store, args)
            self.assertIsNotNone(plan["next_at"])
            client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
            wake = argparse.Namespace(command="wake", dream=False, model=None, host=None)
            with patch("httpx.AsyncClient", return_value=client), redirect_stdout(out):
                await asyncio.wait_for(invoke(wake, self.store), 3)
            result = json.loads(out.getvalue().strip())
            self.assertEqual((result["status"], result["answer"]), ("completed", "scheduled done"))

        asyncio.run(run())

    def test_web_edits_live_data_and_keeps_logs_read_only(self):
        self.store.initialize()
        (self.store.config_path).write_text('{"model":{"api_key":"private-smoke-key"}}')
        server = create_server(self.store, 0)
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}", trust_env=False) as web:
            page = web.get("/")
            self.assertEqual(page.status_code, 200)
            self.assertEqual(web.get("/api/workspace").status_code, 403)
            web.headers["X-Aiverywhere-Token"] = re.search(r'name="session" content="([^"]+)"', page.text)[1]
            before = web.get("/api/workspace")
            self.assertNotIn("private-smoke-key", before.text)
            tag = {"If-None-Match": before.headers["ETag"]}
            self.assertEqual(web.get("/api/workspace", headers=tag).status_code, 304)
            entry = web.post("/api/memory", json={"kind": "fact", "title": "月报", "text": "初稿"}).json()
            path = "/api/memory/" + entry["id"]
            self.assertEqual(web.get("/api/workspace", headers=tag).status_code, 200)
            edit = {"kind": "fact", "title": "月报核对", "text": "完成", "revision": entry["revision"]}
            revision = web.put(path, json=edit).json()["revision"]
            self.assertEqual(web.put(path, json=edit).status_code, 409)
            self.assertEqual(self.store.search("核对", "fact")[0]["id"], entry["id"])
            self.assertEqual(web.request("DELETE", path, json={"revision": revision}).status_code, 200)
            self.assertEqual(web.get(path).status_code, 404)
            self.store.audit("web-smoke", "completed", 1)
            self.assertEqual(web.get("/api/logs").json()["rows"][0]["task_id"], "web-smoke")
            self.assertEqual(web.delete("/api/logs").status_code, 405)
            self.store.audit("web-smoke", "completed", 1, run_id="run-web-smoke",
                             detail={"prompt": "读取 README", "answer": "已读取",
                                     "trace": [{"tool": "read_file", "input": {"path": "README.md"},
                                                "ok": True, "output": "内容"}]})
            self.assertEqual(web.get("/api/logs").json()["rows"][0]["run_id"], "run-web-smoke")
            detailed = web.get("/api/runs/run-web-smoke")
            self.assertEqual(detailed.status_code, 200)
            self.assertEqual(detailed.json()["trace"][0]["tool"], "read_file")
            self.assertEqual(detailed.json()["prompt"], "读取 README")
            agent = before.json()["agent"]
            changed = web.put("/api/agent", json={"revision": agent["revision"], "text": agent["text"] + "\n测试修订。"})
            self.assertEqual(web.request("DELETE", "/api/agent", json={"revision": changed.json()["revision"]}).status_code, 200)
            self.assertEqual(web.get("/api/workspace").json()["agent"]["text"], agent["text"])

    def test_web_agent_bundle_and_durable_session_history(self):
        self.store.initialize()
        ref = self.store.skill_dir / "references" / "web-test.md"
        ref.parent.mkdir(exist_ok=True)
        ref.write_text("原始参考。\n")
        sessions = SessionStore(self.store)
        session = sessions.create()
        turn = session.begin_turn("历史问题")
        session.finish_turn(turn, [
            {"role": "user", "content": "历史问题"},
            {"role": "assistant", "content": "历史回答"}], "历史回答")
        session.release()
        server = create_server(self.store, 0)
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}", trust_env=False) as web:
            page = web.get("/")
            web.headers["X-Aiverywhere-Token"] = re.search(
                r'name="session" content="([^"]+)"', page.text)[1]
            renamed = web.post("/api/sessions/" + session.id + "/rename",
                               json={"name": "Web 历史验收"})
            self.assertEqual(renamed.status_code, 200, renamed.text)
            self.assertEqual(renamed.json()["name"], "Web 历史验收")
            workspace = web.get("/api/workspace").json()
            self.assertEqual(workspace["sessions"][0]["name"], "Web 历史验收")
            files = {item["path"]: item for item in workspace["agent"]["files"]}
            self.assertIn("references/web-test.md", files)
            self.assertEqual(workspace["sessions"][0]["id"], session.id)
            read = web.get("/api/agent/file", params={"path": "references/web-test.md"}).json()
            written = web.put("/api/agent/file", json={
                "path": "references/web-test.md", "revision": read["revision"],
                "text": "更新参考。\n"})
            self.assertEqual(written.status_code, 200, written.text)
            self.assertEqual(ref.read_text(), "更新参考。\n")
            history = web.get("/api/sessions/" + session.id).json()
            self.assertEqual(history["history"][-1]["content"], "历史回答")
            self.assertIn("history", history)

    def test_web_chat_runs_a_task_and_returns_status(self):
        class Provider:
            async def agentloop(self, task, environment, messages, prompt, max_turns, checkpoint, **kwargs):
                return ("网页回答" if not task.writable else "网页回答（可写）"), messages

        self.store.initialize()
        with patch("aiverywhere.integrations.web.chat.executor", return_value=Provider()):
            server = create_server(self.store, 0)
            self.addCleanup(server.server_close)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.shutdown)
            with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}", trust_env=False) as web:
                page = web.get("/")
                web.headers["X-Aiverywhere-Token"] = re.search(
                    r'name="session" content="([^"]+)"', page.text)[1]
                started = web.post("/api/chat", json={
                    "session": "web-chat-session", "message": "你好", "writable": False})
                self.assertEqual(started.status_code, 202, started.text)
                self.assertTrue(started.json()["new_session"])
                state = {}
                for _ in range(80):
                    state = web.get("/api/chat", params={"session": "web-chat-session"}).json()
                    if state.get("status") != "running":
                        break
                    time.sleep(0.02)
                self.assertEqual((state.get("status"), state.get("answer")), ("completed", "网页回答"))
                self.assertEqual(state.get("receipts"), [])
                self.assertEqual(web.post("/api/chat", json={
                    "session": "bad", "message": "x", "writable": False}).status_code, 400)
                self.assertEqual(web.post("/api/chat/reset", json={
                    "session": "web-chat-session"}).status_code, 200)
                self.assertEqual(web.get("/api/chat", params={
                    "session": "web-chat-session"}).json()["status"], "idle")
                writable = web.post("/api/chat", json={
                    "session": "web-chat-writable", "message": "写入模式", "writable": True})
                self.assertEqual(writable.status_code, 202, writable.text)
                state = {}
                for _ in range(80):
                    state = web.get("/api/chat", params={"session": "web-chat-writable"}).json()
                    if state.get("status") != "running":
                        break
                    time.sleep(0.02)
                self.assertEqual((state.get("status"), state.get("answer"),
                                  state.get("writable")), ("completed", "网页回答（可写）", True))
                executable = web.post("/api/chat", json={
                    "session": "web-chat-exec", "message": "执行模式", "writable": False,
                    "exec": True})
                self.assertEqual(executable.status_code, 202, executable.text)
                state = {}
                for _ in range(80):
                    state = web.get("/api/chat", params={"session": "web-chat-exec"}).json()
                    if state.get("status") != "running":
                        break
                    time.sleep(0.02)
                self.assertTrue(state.get("exec_allowed"))
                no_network = web.post("/api/chat", json={
                    "session": "web-chat-network", "message": "无网络", "writable": False,
                    "network": False})
                self.assertEqual(no_network.status_code, 202, no_network.text)
                state = {}
                for _ in range(80):
                    state = web.get("/api/chat", params={"session": "web-chat-network"}).json()
                    if state.get("status") != "running":
                        break
                    time.sleep(0.02)
                self.assertFalse(state.get("network_allowed"))

    def test_wechat_after_compaction_restart_and_lost_receipt(self):
        message = {"account": "test-account", "conversation": "original-chat", "message_id": "incoming-17",
                   "text": "核对月报并答复。"}
        self.store.data.mkdir(parents=True)
        cfg = {"project": str(self.store.project), "url": "https://gateway.invalid",
               "account": message["account"], "conversation": message["conversation"],
               "receipt_lookup": True, "idempotent_send": True}
        (self.store.data / "wechat.json").write_text(json.dumps(cfg))
        (self.store.data / "model.json").write_text(json.dumps({"model": "smoke", "base_url": "https://model.invalid"}))
        key = wechat.receive(self.store, message)["task_id"]
        self.assertEqual(wechat.receive(self.store, message)["task_id"], key)
        with self.assertRaises(ValueError):
            wechat.receive(self.store, message | {"text": "另一项任务"})
        with self.assertRaises(PermissionError):
            wechat.receive(self.store, message | {"conversation": "other-chat"})
        turns, sent, lookups = [], [], []
        script = [("discover", {"kind": "tool", "query": "compact_context"}), ("list_files", {}),
                  ("compact_context", {"summary": "已经找到月报。"}), ("list_files", {}),
                  ("compact_context", {"summary": "证据已核对，摘要中的收件人猜测不可采用。"})]

        def gateway(request):
            if request.url.host == "model.invalid":
                body = json.loads(request.content)
                self.assertEqual(body["messages"][0]["content"], message["text"])
                for private in (message["account"], message["conversation"], message["message_id"]):
                    self.assertNotIn(private, request.content.decode())
                i = len(turns)
                turns.append(len(body["messages"]))
                if i == len(script):
                    return httpx.Response(200, json={"stop_reason": "end_turn",
                        "content": [{"type": "text", "text": "月报已核对。"}]})
                name, args = script[i]
                self.assertIn(name, [spec["name"] for spec in body["tools"]])
                return httpx.Response(200, json={"stop_reason": "tool_use", "content": [
                    {"type": "tool_use", "id": f"t{i}", "name": name, "input": args}]})
            if request.method == "POST":
                sent.append(json.loads(request.content))
                self.assertEqual(request.headers["Idempotency-Key"], key)
                raise httpx.ReadTimeout("模拟网关已接收，回执在途中丢失")
            lookups.append(request.url.path)
            return httpx.Response(200, json=sent[0] | {"receipt": "receipt-17",
                "state": "accepted" if len(lookups) == 1 else "delivered"})

        async def worker():
            restarted = Store(self.store.home, self.project)
            async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as client:
                return await asyncio.wait_for(wechat.process(restarted, client, key), timeout=5)

        self.assertEqual(asyncio.run(worker())["delivery"], "ready")
        saved = self.store.snapshot()["jobs"][key]["result"]
        self.assertEqual((saved["compactions"], saved["answer"]), (2, "月报已核对。"))
        self.assertEqual(turns, [1, 3, 5, 3, 5, 3])
        for elapsed, expected in ((0, "verify"), (10, "accepted"), (20, "delivered")):
            with patch("aiverywhere.integrations.wechat.time.time", return_value=time.time() + elapsed):
                self.assertEqual(asyncio.run(worker())["delivery"], expected)
        self.assertEqual(sent, [{"id": key, "account": message["account"], "conversation": message["conversation"],
                                 "reply_to": message["message_id"], "text": saved["answer"]}])
        self.assertEqual(lookups, ["/messages/" + key] * 2)
        self.assertEqual(json.loads(self.cli("wechat", "--status", key))["receipt"], "receipt-17")
        self.assertEqual(wechat.receive(self.store, message)["delivery"], "delivered")


class RunTraceTest(unittest.TestCase):
    def test_task_run_persists_tool_trace(self):
        import tempfile
        from pathlib import Path
        from aiverywhere.core.agent import Task
        from aiverywhere.core.store import Store

        class Provider:
            async def agentloop(self, task, environment, messages, prompt, max_turns, checkpoint, **kwargs):
                remote = type("Remote", (), {"selected": {}})()
                await task._tool_result({"id": "tool-1", "name": "list_files",
                                         "input": {"path": "."}}, remote)
                return "完成", messages + [{"role": "assistant", "content": "完成"}]

        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            project.mkdir()
            store = Store(Path(root) / "instance", project)
            store.initialize()
            task = Task(store)
            asyncio.run(task.run("列目录", Provider(), max_turns=2, timeout=10))
            detail = store.run_detail(task.run_id)
            self.assertEqual(detail["prompt"], "列目录")
            self.assertEqual(detail["answer"], "完成")
            self.assertEqual(detail["trace"][0]["tool"], "list_files")
            self.assertTrue(detail["trace"][0]["ok"])
            self.assertIn("output", detail["trace"][0])
