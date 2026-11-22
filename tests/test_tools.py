import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from aiverywhere.core.store import Store
from aiverywhere.core.tools import Tools


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.project = root / "project"
        self.project.mkdir()
        self.store = Store(root / "instance", self.project)
        self.store.initialize()
        self.tools = Tools(self.store, "tool-test", writable=True, exec_allowed=True)

    def tearDown(self):
        self.temporary.cleanup()

    def test_search_edit_and_stale_hash(self):
        written = self.tools.write_file("notes.txt", "alpha\nbeta\ngamma\n", "new")
        self.assertEqual(self.tools.search_files("BETA")["results"][0]["line"], 2)
        edited = self.tools.edit_file("notes.txt", "beta", "delta", written["sha256"])
        self.assertEqual(self.tools.read_file("notes.txt")["text"], "alpha\ndelta\ngamma\n")
        with self.assertRaises(ValueError):
            self.tools.edit_file("notes.txt", "delta", "omega", written["sha256"])
        self.assertEqual(edited["bytes"], len("alpha\ndelta\ngamma\n"))

    def test_run_command_returns_exit_code_and_timeout(self):
        result = self.tools.run_command([sys.executable, "-c", "print('tool-ok')"])
        self.assertEqual((result["exit_code"], result["stdout"].strip()), (0, "tool-ok"))
        slow = self.tools.run_command(
            [sys.executable, "-c", "import time; time.sleep(3)"], timeout=1)
        self.assertTrue(slow["timed_out"])
        self.assertNotEqual(slow["exit_code"], 0)

    def test_permissions_remove_write_edit_and_command(self):
        limited = Tools(self.store, "limited", writable=False, exec_allowed=False)
        self.assertNotIn("write_file", limited.available)
        self.assertNotIn("edit_file", limited.available)
        self.assertNotIn("run_command", limited.available)

    def test_execute_dispatches_web_and_command_tools(self):
        rss = b"""<rss><channel><item>
            <title>Python</title><link>https://python.org</link>
            <description>Python documentation</description>
        </item></channel></rss>"""
        response = httpx.Response(200, content=rss,
                                  headers={"content-type": "application/rss+xml"},
                                  request=httpx.Request("GET", "https://www.bing.com/search"))
        with patch("httpx.get", return_value=response):
            result = self.tools.execute("web_search", {"query": "python"})
        self.assertEqual(result["results"][0]["url"], "https://python.org")
        command = self.tools.execute("run_command", {"argv": [sys.executable, "-c", "print('ok')"]})
        self.assertEqual(command["stdout"].strip(), "ok")

    def test_search_web_and_reject_private_fetch(self):
        rss = b"""<rss><channel><item>
            <title>Python</title><link>https://python.org</link>
            <description>Python documentation</description>
        </item></channel></rss>"""
        response = httpx.Response(200, content=rss,
                                  headers={"content-type": "application/rss+xml"},
                                  request=httpx.Request("GET", "https://www.bing.com/search"))
        with patch("httpx.get", return_value=response) as get:
            result = self.tools.web_search("python")
        self.assertEqual(result["results"][0]["url"], "https://python.org")
        self.assertEqual(result["backend"], "bing-rss")
        self.assertEqual(get.call_args.args[0], "https://www.bing.com/search")
        html_page = b'<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F">Example</a>'
        failed = httpx.Response(503, request=httpx.Request("GET", "https://www.bing.com/search"))
        fallback = httpx.Response(200, content=html_page,
                                  request=httpx.Request("GET", "https://html.duckduckgo.com/html/"))
        with patch("httpx.get", side_effect=[failed, fallback]):
            result = self.tools.web_search("example")
        self.assertEqual(result["results"][0]["url"], "https://example.com/")
        self.assertEqual(result["backend"], "duckduckgo-html")
        with self.assertRaises(ValueError):
            self.tools.web_fetch("http://127.0.0.1/secret")


if __name__ == "__main__":
    unittest.main()
