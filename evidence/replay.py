"""Recommission the relabelled winning devices on public streams with the frozen judge."""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmark/engine"))
from b720.certificate import certify
from b720.world import World, generate


def replay():
    case = json.loads((ROOT / "evidence/teaching-replay.json").read_bytes())
    with tempfile.TemporaryDirectory() as directory:
        packet = Path(directory) / "teaching"
        generate(packet, "B", {"master": case["public_stream_seed"], "purpose": "engineering"})
        (packet / "judge/material.json").write_text(json.dumps(case["material"]))
        specimen = World(packet)
        # Carry forward the historical audited observation spend; the teaching
        # replay starts at manufacture and uses publicly generated targets/streams.
        if not specimen.pay(case["research_spend"]):
            raise ValueError("Research spend exhausted the budget.")
        specimen.act({"op": "transfer"})
        for bank, c in enumerate(case["circuits"]):
            if not certify(specimen.material, c)["all_targets_all_ambient_certified"]:
                raise ValueError("Controller failed its symbolic certificate.")
            drives = dict(c["drives"])
            for dest, source, invert in case["wires"]:
                node = drives[dest]
                matches = node >= 740 and c["gates"][node-740] == ["not", source] if invert else node == source
                if not matches:
                    raise ValueError(f"Bank {bank} is missing a verified wiring relation.")
            specimen.act({"op": "install", "bank": bank, "circuit": c})
        startup = specimen.cash
        out = specimen.act({"op": "commission"})
        if not (len(case["wires"]) == 8 and startup == 2 and out["phase"] == "survived"
                and out["installed"] == 8 and all(out["matches"]) and out["frames"] == 100000):
            raise ValueError("Commissioning result changed.")
        return {"working_devices": out["installed"], "frames_per_device": out["frames"],
                "verified_wires_per_device": len(case["wires"]), "startup_capital": startup,
                "model_calls": 0, "streams": "public teaching replay"}


if __name__ == "__main__":
    print(json.dumps(replay(), indent=2))
