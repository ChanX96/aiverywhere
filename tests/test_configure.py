import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from aiverywhere.core.agent import executor
from aiverywhere.core.configure import configure
from aiverywhere.core.store import Store, _linked_home, checked_defaults
from aiverywhere.ui.welcome import FONT, WORDMARK


class Configure(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = Store(self.root / "install", self.project)

    def config(self):
        return json.loads((self.store.config_path).read_text())

    def test_initialize_migrates_legacy_data_config(self):
        self.store.data.mkdir(parents=True, exist_ok=True)
        (self.store.data / "SKILL.md").write_text("---\nname: test\ndescription: test\n---\n正文")
        (self.store.data / "config.json").write_text(json.dumps({
            "model": {"model": "legacy", "base_url": "http://legacy.invalid", "api_key": "legacy-key"}}))
        info = self.store.initialize()
        self.assertEqual(info["config"], str(self.store.config_path))
        self.assertFalse((self.store.data / "config.json").exists())
        self.assertEqual(json.loads(self.store.config_path.read_text())["model"]["model"], "legacy")
        self.assertEqual(stat.S_IMODE(self.store.config_path.stat().st_mode), 0o600)
        (self.store.data / "config.json").write_text(json.dumps({"defaults": {}}))
        with self.assertRaises(ValueError):
            self.store.initialize()

    def test_noninteractive_writes_model_defaults_and_preserves_other_sections(self):
        self.store.initialize()
        (self.store.config_path).write_text(json.dumps({
            "model": {}, "mcpServers": {"office": {"command": "office"}},
            "wechat": {"project": str(self.project)}}))
        result = configure(self.store, no_input=True, model="demo", base_url="http://127.0.0.1:9000",
                           api_key="top-secret", max_tokens=2048, max_turns=4, timeout=30, port=0)
        config = self.config()
        self.assertEqual(config["model"], {"model": "demo", "base_url": "http://127.0.0.1:9000",
                                           "api_key": "top-secret", "max_tokens": 2048})
        self.assertEqual(config["defaults"], {"max_turns": 4, "timeout": 30, "port": 0})
        self.assertEqual(config["mcpServers"], {"office": {"command": "office"}})
        self.assertEqual(config["wechat"], {"project": str(self.project)})
        self.assertEqual(stat.S_IMODE((self.store.config_path).stat().st_mode), 0o600)
        self.assertNotIn("top-secret", json.dumps(result, ensure_ascii=False))

    def test_environment_credential_is_referenced_without_copying_the_secret(self):
        self.store.initialize()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env-secret", "ANTHROPIC_AUTH_TOKEN": ""}):
            configure(self.store, no_input=True, model="demo", base_url="http://127.0.0.1:9000")
        self.assertEqual(self.config()["model"],
                         {"model": "demo", "base_url": "http://127.0.0.1:9000",
                          "api_key_env": "ANTHROPIC_API_KEY"})

    def test_official_endpoint_requires_a_credential(self):
        self.store.initialize()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": ""}):
            with self.assertRaises(ValueError):
                configure(self.store, no_input=True, model="demo")

    def test_interactive_defaults_and_runtime_override(self):
        inputs = ["", "", "demo-model", "", "", "y", "6", "", "", ""]
        with patch("builtins.input", side_effect=inputs), patch("getpass.getpass", return_value="secret"), \
                redirect_stdout(io.StringIO()):
            configure(self.store, interactive=True)
        config = self.config()
        self.assertEqual(config["model"], {"model": "demo-model", "api_key": "secret"})
        self.assertEqual(config["defaults"], {"max_turns": 6, "timeout": 180, "port": 8765})

    def test_link_is_idempotent_and_refuses_a_foreign_file(self):
        self.store.initialize()
        first = self.store.link_agent()
        target = Path(first["path"])
        self.assertTrue(target.is_symlink())
        self.assertIn(target.resolve(), {self.store.agent_file.resolve(),
                                         self.store.skill_dir.resolve()})
        self.assertEqual(_linked_home(self.project), self.store.home.resolve())
        self.assertFalse(self.store.link_agent()["created"])
        target.unlink()
        target.symlink_to(self.root / "gone/SKILL.md")
        self.assertTrue(self.store.link_agent()["created"])
        target.unlink()
        target.write_text("other project")
        with self.assertRaises(ValueError):
            self.store.link_agent()

    def test_cli_exposes_slash_command_menu(self):
        from aiverywhere.cli.main import SLASH_COMMANDS, _slash_matches
        commands = {command for command, _ in SLASH_COMMANDS}
        self.assertEqual(commands, {"/help", "/new", "/resume", "/rename", "/sessions", "/status", "/compact", "/permissions", "/grant", "/revoke", "/approve", "/deny", "/jobs", "/cancel", "/ask", "/quit"})
        self.assertEqual({command for command, _ in _slash_matches("/")}, commands)
        self.assertEqual([command for command, _ in _slash_matches("/he")], ["/help"])

    def test_setup_protocol_flags_parse(self):
        from aiverywhere.cli.main import parser
        args = parser().parse_args(["setup", "--protocol", "openai",
                                    "--chat-path", "/v1/chat/completions"])
        self.assertEqual(args.protocol, "openai")
        self.assertEqual(args.chat_path, "/v1/chat/completions")

    def test_root_interactive_permission_flags_parse(self):
        from aiverywhere.cli.main import parser
        args = parser().parse_args(["--allow-write", "--allow-exec"])
        self.assertTrue(args.root_allow_write)
        self.assertTrue(args.root_allow_exec)

    def test_session_settings_are_validated(self):
        self.store.initialize()
        self.assertEqual(self.store.session_settings()["compact_at"], 0.8)
        self.store.config_path.write_text('{"session":{"compact_at":1.2}}')
        with self.assertRaises(ValueError):
            self.store.session_settings()

    def test_welcome_wordmark_is_generated_from_exact_letters(self):
        self.assertEqual(WORDMARK, "AIVERYWHERE")
        self.assertTrue(set(WORDMARK) <= set(FONT))
        self.assertTrue(all(len(rows) == 7 for rows in FONT.values()))
        self.assertTrue(all(len(row) == 5 for rows in FONT.values() for row in rows))

    def test_defaults_are_validated_and_reach_the_messages_client(self):
        with self.assertRaises(ValueError):
            checked_defaults({"max_turns": True})
        with self.assertRaises(ValueError):
            checked_defaults({"port": 70000})
        self.store.data.mkdir(mode=0o700, parents=True)
        (self.store.config_path).write_text(json.dumps(
            {"model": {"model": "demo", "base_url": "https://example.test", "max_tokens": 777}}))
        provider = executor(object(), None, self.store)
        self.assertEqual(provider.max_tokens, 777)
        (self.store.config_path).write_text(json.dumps(
            {"model": {"model": "demo", "api_key": "a", "auth_token": "b"}}))
        with self.assertRaises(ValueError):
            executor(object(), None, self.store)
        (self.store.config_path).write_text(json.dumps(
            {"model": {"model": "demo", "api_key_env": "SMOKE_KEY"}}))
        with patch.dict(os.environ, {"SMOKE_KEY": "from-env"}):
            provider = executor(object(), None, self.store)
        self.assertEqual(provider.headers["x-api-key"], "from-env")


class CommandLine(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.home = self.root / "install"
        self.source = Path(__file__).resolve().parents[1] / "src"

    def cli(self, *args):
        env = dict(os.environ, PYTHONPATH=str(self.source), ANTHROPIC_API_KEY="", ANTHROPIC_AUTH_TOKEN="")
        return subprocess.run([sys.executable, "-m", "aiverywhere", "--home", str(self.home),
                               "--project", str(self.project), *args],
                              cwd=self.project, env=env, text=True, capture_output=True, check=False)

    def test_welcome_shows_state_without_exposing_credentials(self):
        fresh = self.cli("welcome")
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        self.assertIn("尚未初始化", fresh.stdout)
        self.assertEqual(self.cli("init").returncode, 0)
        setup = self.cli("setup", "--no-input", "--model", "demo", "--base-url", "http://127.0.0.1:9000",
                         "--api-key", "private-welcome-key")
        self.assertEqual(setup.returncode, 0, setup.stderr)
        welcome = self.cli("welcome")
        self.assertEqual(welcome.returncode, 0, welcome.stderr)
        self.assertIn("demo", welcome.stdout)
        self.assertIn("项目", welcome.stdout)
        self.assertNotIn("private-welcome-key", welcome.stdout)
        no_args = self.cli()
        self.assertEqual(no_args.returncode, 0, no_args.stderr)
        self.assertIn("aiverywhere", no_args.stdout)

    def test_setup_and_link_share_the_same_instance(self):
        version = self.cli("--version")
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertIn("aiverywhere 0.3.0", version.stdout)
        setup = self.cli("setup", "--no-input", "--model", "demo", "--base-url", "http://127.0.0.1:9000",
                         "--api-key", "secret", "--max-turns", "3", "--port", "0")
        self.assertEqual(setup.returncode, 0, setup.stderr)
        self.assertEqual(json.loads(setup.stdout)["defaults"], {
            "max_turns": 3, "timeout": 180, "port": 0})
        link = self.cli("link")
        self.assertEqual(link.returncode, 0, link.stderr)
        target = Path(json.loads(link.stdout)["path"])
        self.assertTrue(target.is_symlink())
        self.assertEqual(target.resolve(), (self.home / "data/SKILL.md").resolve())
        again = self.cli("link")
        self.assertFalse(json.loads(again.stdout)["created"])


class AgentBundleTest(unittest.TestCase):
    def test_bundle_files_are_listed_and_edited_with_revision_checks(self):
        import tempfile
        from pathlib import Path
        from aiverywhere.core.store import Store

        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            project.mkdir()
            store = Store(Path(root) / "instance", project)
            store.initialize()
            ref_dir = store.skill_dir / "references"
            ref_dir.mkdir(exist_ok=True)
            (ref_dir / "test.md").write_text("原始。\n")
            paths = {item["path"] for item in store.agent_files()}
            self.assertIn("SKILL.md", paths)
            self.assertIn("references/test.md", paths)
            item = store.read_agent_file("references/test.md")
            updated = store.write_agent_file(
                "references/test.md", item["text"] + "补充。\n", item["revision"])
            self.assertTrue(store.read_agent_file("references/test.md")["text"].endswith("补充。\n"))
            with self.assertRaises(ValueError):
                store.write_agent_file("references/test.md", "stale", item["revision"])
            with self.assertRaises(ValueError):
                store.read_agent_file("../config.json")
            with self.assertRaises(ValueError):
                store.read_agent_file("references/../SKILL.md")
            self.assertTrue(updated["revision"])


class ResumeOptionTest(unittest.TestCase):
    def test_chat_accepts_a_durable_session_id(self):
        from aiverywhere.cli.main import parser
        ident = "a" * 32
        args = parser().parse_args(["chat", "--resume", ident])
        self.assertEqual(args.resume, ident)
        self.assertEqual(parser().parse_args(["chat", "--resume"]).resume, "")
