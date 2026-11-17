"""The teaching control must preserve the device's assigned target when inputs change."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmark/engine"))
from b720.circuits import evaluate, validate
from b720.world import bits, response


class TeachingFigure(unittest.TestCase):
    def test_each_displayed_response_is_physical(self):
        evidence = ROOT / "evidence"
        case = json.loads((evidence / "teaching-replay.json").read_bytes())
        samples = json.loads((evidence / "teaching-figure.json").read_bytes())
        circuit = validate(case["circuits"][0], 720, 20)
        self.assertGreater(len({s["input"] for s in samples}), 1)
        for sample in samples:
            with self.subTest(sample=sample["input"][:12]):
                ambient = list(map(int, sample["input"]))
                target = samples[0]["target"]
                self.assertEqual(sample["target"], target)
                self.assertEqual(len(ambient), 720)
                self.assertEqual(sample["before"], bits(response(case["material"], ambient + target), 20))
                x = evaluate(circuit, ambient, target, 1)
                self.assertEqual(sample["after"], bits(response(case["material"], x), 20))
                self.assertEqual(sample["after"], target)
