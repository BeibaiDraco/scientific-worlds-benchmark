import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
from provider import parse_reply


class ProviderContract(unittest.TestCase):
    def test_reply_and_usage(self):
        payload = {"model": "m", "choices": [{"message": {"content": "FINISH"}}],
                   "usage": {"completion_tokens": 7}}
        self.assertEqual(parse_reply(payload, "m"), ("FINISH", 7))
        with self.assertRaises(ValueError):
            parse_reply(payload, "different")
        del payload["usage"]
        with self.assertRaises(ValueError):
            parse_reply(payload, "m")
