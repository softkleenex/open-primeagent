"""Does fan-out win when each child has minutes of blocking work to do?

This is the case our earlier benchmarks named and did not test. Fan-out lost on
a 12-file project and on a 444-file one, both times because a child's ~36k-token,
~30-second startup had nothing to amortise against: a competent agent greps
instead of reading, so the bottleneck fan-out relieves never formed.

Here it does. Four subsystems, each with one small planted bug and an acceptance
check that blocks for ~45s before it can report -- the shape of a build. Serial
time cannot be grepped away.

    single   one agent fixes all four; it pays every check sequentially
    fanout   one child per subsystem, all four blocking at once

Tokens are not the question. With four children the startup is paid four times
by construction, and we have said so since benchmark 0. The question is whether
the wall clock finally goes the other way, and what that latency costs.

    uv run python bench/serial.py --repeat 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from slowsuite import SUBSYSTEMS, SUITE_SECONDS, build, verify

from opa.config import Config
from opa.server import build_server

CHILD_TASK = (
    "In this repository, {name}/core.py has a bug: {hint}. Fix {name}/core.py so "
    "that `python3 {name}/check.py` exits 0. The check takes about {seconds} "
    "seconds to run, which is expected — wait for it. Do NOT edit {name}/check.py. "
    "Reply with only DONE when it passes."
)
SINGLE_TASK = (
    "This repository has four subsystems: {names}. Each has one bug in its "
    "core.py, and an acceptance check `python3 <name>/check.py` that must exit 0. "
    "Each check takes about {seconds} seconds to run, which is expected — wait for "
    "them. Fix all four. Do NOT edit any check.py. Reply with only DONE when all "
    "four pass."
)


@dataclass
class Run:
    arm: str
    seconds: int = 0        # how long each check blocks; conditions are not comparable across values
    child_tokens: int = 0
    child_cost: float = 0.0
    children: int = 0
    duration_ms: int = 0
    passed: int = 0
    passing: list[str] = field(default_factory=list)
    tampered: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def make_config(workspace: Path) -> Config:
    return Config(
        root=workspace / ".opa",
        global_root=workspace / ".opa-global",
        workspace=workspace,
        max_output_chars=4000,
        default_adapter="claude-code",
        child_permission_mode="acceptEdits",
        child_allowed_tools=("Bash", "Read", "Edit", "Write", "Grep", "Glob"),
        allow_dangerous_child=False,
        child_can_message_parent=False,
    )


async def call(server, code: str) -> str:
    return (await server.call_tool("opa_python", {"code": code})).content[0].text


async def wait_for_inbox(runtime, count: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while runtime.rlm.mailbox.count() < count:
        if time.monotonic() > deadline:
            raise TimeoutError(f"mailbox never reached {count}")
        await asyncio.sleep(2)


async def run_arm(arm: str, model: str, seconds: int, timeout: float) -> Run:
    workspace = Path(tempfile.mkdtemp(prefix=f"opa-serial-{arm}-")) / "platform"
    digests = build(workspace, seconds=seconds)
    server = build_server(make_config(workspace))
    runtime = server._opa_runtime
    try:
        started = time.monotonic()
        if arm == "fanout":
            for name, (_, _, _, hint) in SUBSYSTEMS.items():
                prompt = CHILD_TASK.format(name=name, hint=hint, seconds=seconds)
                await call(
                    server, f"await rlm({prompt!r}, name={name!r}, model={model!r})"
                )
            await wait_for_inbox(runtime, len(SUBSYSTEMS), timeout)
        else:
            prompt = SINGLE_TASK.format(
                names=", ".join(SUBSYSTEMS), seconds=seconds
            )
            await call(server, f"await rlm({prompt!r}, name='fixer', model={model!r})")
            await wait_for_inbox(runtime, 1, timeout)
        elapsed = int((time.monotonic() - started) * 1000)

        records = runtime.rlm.registry.list()
        graded = verify(workspace, digests, seconds=0)
        return Run(
            arm=arm,
            seconds=seconds,
            child_tokens=sum(r.tokens for r in records),
            child_cost=round(sum(r.cost_usd for r in records), 6),
            children=len(records),
            duration_ms=elapsed,
            passed=int(graded["passed"]),
            passing=list(graded["passing"]),
            tampered=list(graded["tampered"]),
            errors=[r.name for r in records if r.status == "error"],
        )
    finally:
        await runtime.shutdown()
        shutil.rmtree(workspace.parent, ignore_errors=True)


async def main_async(args) -> None:
    print(
        f"{len(SUBSYSTEMS)} subsystems, each check blocks ~{args.seconds}s "
        f"(serial floor for one agent: ~{args.seconds * len(SUBSYSTEMS)}s)"
    )
    rows: list[Run] = []
    for attempt in range(args.repeat):
        for arm in ("single", "fanout"):
            print(f"[{arm}] attempt {attempt + 1}/{args.repeat} …", flush=True)
            row = await run_arm(arm, args.model, args.seconds, args.timeout)
            print(
                f"    {row.duration_ms / 1000:6.1f}s  tokens={row.child_tokens:,} "
                f"cost=${row.child_cost}  passed={row.passed}/4 "
                f"tampered={row.tampered} errors={row.errors}",
                flush=True,
            )
            rows.append(row)

    out = Path(args.out) / f"serial-{args.model}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    out.write_text(
        json.dumps(previous + [asdict(r) for r in rows], indent=2), encoding="utf-8"
    )
    print(f"wrote {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--seconds", type=int, default=SUITE_SECONDS)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--out", default=str(Path(__file__).parent / "results"))
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
