"""Warm child versus cold child, with the host agent removed from the loop.

The first attempt at this drove both arms through `claude -p` and asked it to
re-task an existing sub-agent. `child_turns` showed it usually did not: the
parent answered from the earlier report sitting in its own context, so the
experiment was measuring the parent's discretion rather than the thing named in
its title. Those results are kept in
`results/subagents-warm-INVALID-host-driven.json`.

Here the host agent is gone. We drive the opa MCP server in-process and execute
a fixed snippet, so the only difference between the arms is `agent_message.send`
to a child that already read the file versus `rlm()` for one that has not.

    uv run python bench/warm.py --repeat 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from project import build

from opa.config import Config
from opa.server import build_server

SETUP = (
    "Read api/auth.py closely, line by line. Report every problem you find - "
    "security vulnerabilities, bugs, logic errors, bad practices - with "
    "file:line references and a short explanation for each."
)
FOLLOWUP = (
    "Of the problems in api/auth.py, which one would you fix first, and what "
    "exactly would the fixed code look like?"
)


@dataclass
class Result:
    arm: str
    child_tokens: int
    child_cost: float
    duration_ms: int
    answer_chars: int
    ok: bool


async def call(server, code: str) -> str:
    return (await server.call_tool("opa_python", {"code": code})).content[0].text


async def wait_for_inbox(runtime, count: int, timeout: float = 600) -> None:
    deadline = time.monotonic() + timeout
    while runtime.rlm.mailbox.count() < count:
        if time.monotonic() > deadline:
            raise TimeoutError(f"mailbox never reached {count}")
        await asyncio.sleep(1)


def child_totals(runtime, name: str) -> tuple[int, float, int]:
    record = runtime.rlm.registry.get(name)
    if record is None:
        return 0, 0.0, 0
    return record.tokens, record.cost_usd, record.turns


async def run_arm(arm: str, model: str) -> Result:
    workspace = Path(tempfile.mkdtemp(prefix=f"opa-warm-{arm}-")) / "svc"
    build(workspace)
    config = Config(
        root=workspace / ".opa",
        global_root=workspace / ".opa-global",
        workspace=workspace,
        max_output_chars=4000,
        default_adapter="claude-code",
        child_permission_mode="acceptEdits",
        child_allowed_tools=("Bash", "Read", "Edit", "Write", "Grep", "Glob"),
        allow_dangerous_child=False,
    )
    server = build_server(config)
    runtime = server._opa_runtime
    try:
        # Both arms pay for the same setup child; it is not measured.
        await call(server, f"await rlm({SETUP!r}, name='reviewer', model={model!r})")
        await wait_for_inbox(runtime, 1)
        base_tokens, base_cost, base_turns = child_totals(runtime, "reviewer")

        started = time.monotonic()
        if arm == "warm":
            await call(
                server,
                f"await agent_message.send({FOLLOWUP!r}, receiver_name='reviewer')",
            )
            target = "reviewer"
        else:
            cold_prompt = f"Read api/auth.py. {FOLLOWUP}"
            await call(
                server, f"await rlm({cold_prompt!r}, name='reviewer-2', model={model!r})"
            )
            target = "reviewer-2"
        await wait_for_inbox(runtime, 2)
        elapsed = int((time.monotonic() - started) * 1000)

        tokens, cost, turns = child_totals(runtime, target)
        if arm == "warm":
            tokens -= base_tokens
            cost = round(cost - base_cost, 6)
            turns -= base_turns
        answer = runtime.rlm.mailbox.read()[-1]
        return Result(
            arm=arm,
            child_tokens=tokens,
            child_cost=cost,
            duration_ms=elapsed,
            answer_chars=len(answer["message"]),
            # turns must have advanced, or the child never actually ran
            ok=bool(answer.get("ok")) and turns == 1,
        )
    finally:
        await runtime.shutdown()
        shutil.rmtree(workspace.parent, ignore_errors=True)


async def main_async(args) -> None:
    rows: list[Result] = []
    for attempt in range(args.repeat):
        for arm in ("cold", "warm"):
            print(f"[{arm}] attempt {attempt + 1}/{args.repeat} …", flush=True)
            row = await run_arm(arm, args.model)
            print(
                f"    child_tokens={row.child_tokens:,} cost=${row.child_cost} "
                f"{row.duration_ms:,}ms answer={row.answer_chars} chars ok={row.ok}",
                flush=True,
            )
            rows.append(row)

    out = Path(args.out) / f"warm-{args.model}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    out.write_text(
        json.dumps(previous + [asdict(r) for r in rows], indent=2), encoding="utf-8"
    )
    print(f"wrote {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--out", default=str(Path(__file__).parent / "results"))
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
