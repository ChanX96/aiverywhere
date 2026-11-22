import json
import unittest
from pathlib import Path

from aiverywhere.core.memory import valid_record


class MemoryVectors(unittest.TestCase):
    def test_python_and_shell_share_vectors(self):
        path = Path(__file__).resolve().parent / "fixtures/memory-v1-vectors.json"
        cases = json.loads(path.read_text())["cases"]
        for case in cases:
            with self.subTest(case=case["name"]):
                errors = valid_record(case["record"])
                self.assertEqual(not errors, case["valid"], errors)
