"""Run one self-hosted session, verify the Linux worker, or replay a saved session."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import signal
import sys
import time
from contextlib import contextmanager

from binding import capture_runtime
from console import Console
from provider import completion, parse_reply

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "benchmark/engine"
sys.path.insert(0, str(ENGINE))
from b720 import integrity, resources, world

FENCE = re.compile(r"^[ \t]*`{3,}(?:python|py)?[ \t]*\r?\n(.*?)^[ \t]*`{3,}[ \t]*\r?$", re.M | re.S)


def write(path, obj):
    temp = path.with_suffix(path.suffix + ".partial")
    with temp.open("x") as fp:
        json.dump(obj, fp, indent=2, allow_nan=False)
        fp.write("\n")
    temp.replace(path)


def read(path):
    return json.loads(path.read_bytes())


@contextmanager
def time_left(seconds):
    def stop(signum, frame):
        raise TimeoutError("Model call exceeded the session deadline.")
    previous = signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, max(.001, seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def setup(run, family, arm, seed, seconds, turns):
    if sys.platform != "linux" or os.geteuid() == 0:
        raise RuntimeError("Use an unprivileged account on an x86-64 Linux host.")
    for part in ("records", "work", "history"):
        (run / part).mkdir(mode=0o700)
    runtime = capture_runtime(run / "runtime.json")
    mounts = [Path("/usr"), Path(runtime["base_prefix"]), Path(runtime["scientific_path"])]
    if any(path.is_relative_to(m) for path in (ROOT, run) for m in mounts):
        raise ValueError("Keep the checkout and run outside the worker's read-only runtime mounts.")
    packet = run / "instance"
    world.generate(packet, family, {"master": seed, "purpose": "engineering"})
    write(run / "commitment.json", {"packets": {"instance": {"grade": family, "hashes": integrity.hashes(packet)}}})
    console = Console(packet, run / "records", run / "work", arm, time.monotonic() + seconds,
                      run / "history", release=ENGINE, commitment=run / "commitment.json",
                      runtime=run / "runtime.json", core=min(os.sched_getaffinity(0)))
    console.turn_limit = turns
    template = ROOT / "benchmark/prompts" / f"neural-{family}-{arm}.txt"
    if template.read_bytes() != console.initial_prompt.encode():
        raise ValueError("Initial condition prompt differs from the release.")
    return console


def replay(run, expected=None):
    packet = run / "instance"
    integrity.verify_packet(packet, run / "commitment.json")
    simulation = world.World(packet)
    log = run / "records/physical.jsonl"
    count = 0
    if log.exists():
        with log.open() as fp:
            for count, line in enumerate(fp, 1):
                entry = json.loads(line)
                if simulation.act(entry["request"]) != entry["result"]:
                    raise ValueError(f"Physical replay differs at action {count}.")
    state = simulation.state()
    expected = read(run / "result.json") if expected is None else expected
    if state != expected["physical_state"]:
        raise ValueError("Replayed terminal state differs.")
    score = int(state["phase"] == "survived")
    if expected["delivery"] is not None and expected["delivery"] != score:
        raise ValueError("Delivery differs on replay.")
    return {"replayed_actions": count, "phase": state["phase"], "delivery": expected["delivery"]}


def qualify(console):
    code = """import os, scipy
assert sorted(os.listdir('/work')) == ['MICRO_PRIOR.en.md', 'RULES.md', 'task.json']
assert not os.path.exists('/instance')
assert 'SW_API_KEY' not in os.environ
print('WORKER_OK', act('observe', x=[0]*740)['reading'])
"""
    result = console.run(code, 1)
    if result["exit_code"] != 0 or "WORKER_OK" not in result["stdout"] or console.w.shots != 1:
        raise RuntimeError("Public worker probe failed. Inspect records.")
    return "worker-qualified"


def evaluate(console, args, run):
    history = []
    for turn in range(1, console.turn_limit + 1):
        remaining = console.budget()
        seconds = remaining["wall_seconds_remaining"]
        tokens = remaining["known_generated_tokens_remaining"]
        if seconds <= 0 or tokens <= 0 or remaining["worker_cpu_seconds_remaining"] <= 0:
            return "budget-exhausted"
        prompt = console.prompt(history)
        if args.turns != resources.TURNS or args.seconds != resources.WALL_SECONDS:
            prompt += f"\nOperator development cap: {args.turns} turns and {args.seconds} wall seconds."
        if args.command == "exercise":
            if console.w.shots == 0:
                program = "print(act('observe', x=[0] * 740)['reading'])"
            else:
                program = "print(act('transfer')['phase'])\nprint(act('commission')['phase'])"
            prompt += ("\nThis is a public integration check. The operator supplies the action sequence. "
                       "Return the following Python block exactly, including the code fences.\n"
                       + "```python\n" + program + "\n```")
        write(run / "records" / f"request_{turn:06}.json", {
            "model": args.model, "prompt": prompt, "remaining": remaining,
            "max_tokens": min(tokens, args.reply_tokens)})
        with time_left(seconds):
            raw = completion(args.base_url, args.model, prompt, min(tokens, args.reply_tokens), seconds)
        write(run / "records" / f"response_{turn:06}.json", raw)
        message, used = parse_reply(raw, args.model)
        console.turn = turn
        console.tokens += used
        if console.tokens > resources.TOKEN_LIMIT or time.monotonic() >= console.deadline:
            return "budget-exhausted"
        if message.strip() == "FINISH":
            return "participant-finished"
        blocks = FENCE.findall(message)
        if len(blocks) == 1:
            result = console.run(blocks[0], turn)
            visible = {"stdout": result["stdout"], "exit_code": result["exit_code"], "ledger": console.state()}
        else:
            visible = {"error": "Return one fenced Python block, or FINISH."}
        record = {"turn": turn, "reply": message, "result": visible}
        write(run / "history" / f"turn_{turn:06}.json", record)
        history.append(record)
        if console.w.phase in ("dead", "survived"):
            return console.w.phase
    return "turn-cap"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("qualify", "run", "exercise", "replay"):
        cmd = sub.add_parser(name)
        cmd.add_argument("directory", type=Path)
        if name in ("run", "exercise"):
            cmd.add_argument("--condition", choices=["M", "N0", "F"], default="M")
            cmd.add_argument("--family", choices=["B", "S", "C"], default="B")
            cmd.add_argument("--seed", type=int, help="Operator-only seed. Generated if omitted.")
            cmd.add_argument("--base-url", required=True)
            cmd.add_argument("--model", required=True, help="Exact response model identifier")
            cmd.add_argument("--turns", type=int, default=resources.TURNS)
            cmd.add_argument("--seconds", type=int, default=resources.WALL_SECONDS)
            cmd.add_argument("--reply-tokens", type=int, default=8192)
    args = parser.parse_args()
    run = args.directory.resolve()
    if args.command == "replay":
        print(json.dumps(replay(run), indent=2))
        return
    testing = args.command == "qualify"
    if testing:
        args.family, args.condition, args.seed, args.turns, args.seconds = "B", "M", 101, 1, 180
    elif not (0 < args.turns <= resources.TURNS and 0 < args.seconds <= resources.WALL_SECONDS
              and 0 < args.reply_tokens <= resources.TOKEN_LIMIT):
        parser.error("Development limits must be positive and within the release contract.")
    if args.command == "exercise":
        args.family, args.condition, args.seed = "B", "M", 101
    run.mkdir(mode=0o700, parents=True, exist_ok=False)
    seed = args.seed if args.seed is not None else secrets.randbits(128)
    config = {"schema": 1, "track": {"qualify": "worker-check", "exercise": "guided-integration", "run": "self-reported"}[args.command],
              "family": args.family, "condition": args.condition, "seed": seed,
              "model": getattr(args, "model", None), "turn_budget": args.turns,
              "wall_budget_seconds": args.seconds, "reply_token_limit": getattr(args, "reply_tokens", None),
              "formal_score_eligible": False}
    write(run / "config.json", config)
    console = None
    try:
        console = setup(run, args.family, args.condition, seed, args.seconds, args.turns)
        status = qualify(console) if testing else evaluate(console, args, run)
        result = {"status": status, "delivery": None if testing else int(console.w.phase == "survived"),
                  "physical_state": console.w.state(), "worker_cpu_seconds": console.cpu,
                  "model_turns": console.turn if not testing else 0,
                  "worker_blocks": len(list((run/"records").glob("receipt_*.json"))),
                  "active_seconds": round(args.seconds - console.budget()["wall_seconds_remaining"], 3),
                  "reported_generated_tokens": console.tokens, "formal_score_eligible": False}
        result["replay"] = replay(run, result)
        result["track"] = config["track"]
        if args.command == "exercise" and not (
            console.w.shots >= 1 and console.w.phase == "dead" and result["worker_blocks"] >= 2
            and result["replay"]["replayed_actions"] >= 3
        ):
            raise RuntimeError("Guided integration did not complete observation, transfer and commissioning.")
    except BaseException as error:
        result = {"status": "unresolved", "delivery": None, "error": f"{type(error).__name__}: {error}",
                  "physical_state": console.w.state() if console else None,
                  "known_generated_tokens": console.tokens if console else None,
                  "usage_complete": False, "formal_score_eligible": False}
        write(run / "result.json", result)
        raise
    write(run / "result.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
