"""Rebuild the release scorecard from individual accepted sessions (no model calls)."""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def scorecard():
    rows = json.loads((HERE / "sessions.json").read_bytes())
    if len({r["session"] for r in rows}) != len(rows):
        raise ValueError("Duplicate session.")
    conditions = {arm: {"successes": 0, "sessions": 0} for arm in ("M", "N0", "F")}
    for row in rows:
        value = row["delivered"]
        if type(value) is not int or value not in (0, 1):
            raise ValueError("Invalid delivery.")
        cell = conditions[row["condition"]]
        cell["successes"] += value
        cell["sessions"] += 1
    for cell in conditions.values():
        cell["percent"] = 100 * cell["successes"] / cell["sessions"]
    return {"version": "1.0.0", "model": "gpt-6-astra", "effort": "max",
            "unit": "scored session", "budget_hours": sorted({r["budget_hours"] for r in rows}),
            "conditions": conditions, "distinct_M_success_worlds": len({
                r["world"] for r in rows if r["condition"] == "M" and r["delivered"]})}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare against the published scorecard.")
    args = parser.parse_args()
    result = scorecard()
    if args.check and result != json.loads((HERE / "scorecard.json").read_bytes()):
        raise SystemExit("Recalculated results differ from the published scorecard.")
    if args.check:
        cells = []
        for arm in ("M", "N0", "F"):
            cell = result["conditions"][arm]
            label = f'{cell["percent"]:g}% ({cell["successes"]}/{cell["sessions"]})'
            cells.append(f"**{label}**" if arm == "M" else label)
        row = "| Astra 6.0 Max · 10–12 active hours | " + " | ".join(cells) + " |"
        if row not in (HERE.parent / "README.md").read_text().splitlines():
            raise SystemExit("README table differs from the session records.")
    print(json.dumps(result, indent=2))
