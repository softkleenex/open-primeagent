"""The decisive fan-out test: a large codebase split into independent subsystems.

Benchmark 0 fanned four children at a 12-file project and lost by 8.8x. That
setup was rigged against fan-out twice over: the material was trivial, and every
child re-read the whole project. This one removes both objections — 444 files,
~135k tokens, four independently ownable subsystems, and each child scoped to
exactly one so nothing is read twice.

**What this can and cannot show.** If children are scoped, the reading is the
same either way, so fan-out spends three extra session startups (~108k tokens)
by construction. It therefore cannot win on total tokens, and we do not test
whether it does. The hypotheses worth testing are:

    H1  fan-out reduces wall clock, because independent subsystems run at once
    H2  fan-out finds more, because each child holds one subsystem instead of four

Each subsystem carries exactly one planted defect, so H2 is gradeable rather
than a judgement about prose.

    uv run python bench/fanout.py --repeat 2
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
from bigrepo import SUBSYSTEMS, approximate_tokens, build

from opa.config import Config
from opa.server import build_server

REPO = Path(__file__).resolve().parent.parent

DIMENSION_PROMPT = (
    "Review ONLY the {subsystem}/ directory of this repository ({role}). "
    "Find the single most serious defect in it. Reply with the file path and one "
    "sentence naming the specific problem."
)
WHOLE_PROMPT = (
    "Review this repository. It has four subsystems: auth/, billing/, catalog/ "
    "and delivery/. Find the single most serious defect in EACH of the four and "
    "reply with four lines, each giving a file path and one sentence naming the "
    "specific problem."
)

# What counts as having found each planted defect. Keyword matching is crude but
# reproducible, and it does not reward confident prose.
MARKERS = {
    "auth": ["signing_key", "signing key", "hardcoded", "hard-coded", "secret"],
    "billing": ["float", "floating point", "decimal", "rounding"],
    "catalog": ["sql injection", "concatenat", "string interpolation", "parameteri"],
    "delivery": ["quadratic", "o(n^2)", "o(n2)", "nested loop", "n^2"],
}


@dataclass
class Run:
    arm: str
    parent_tokens: int = 0
    parent_cost: float = 0.0
    child_tokens: int = 0
    child_cost: float = 0.0
    children: int = 0
    child_turns: int = 0
    duration_ms: int = 0
    found: list[str] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)
    ok: bool = True

    @property
    def total_tokens(self) -> int:
        return self.parent_tokens + self.child_tokens

    @property
    def total_cost(self) -> float:
        return round(self.parent_cost + self.child_cost, 6)


def grade(text: str) -> list[str]:
    lowered = text.lower()
    return [
        subsystem
        for subsystem, markers in MARKERS.items()
        if any(marker in lowered for marker in markers)
    ]


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
    )


async def call(server, code: str) -> str:
    return (await server.call_tool("opa_python", {"code": code})).content[0].text


async def wait_for_inbox(runtime, count: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while runtime.rlm.mailbox.count() < count:
        if time.monotonic() > deadline:
            raise TimeoutError(f"mailbox never reached {count}")
        await asyncio.sleep(2)


def registry_totals(runtime) -> tuple[int, float, int, int]:
    records = runtime.rlm.registry.list()
    return (
        sum(r.tokens for r in records),
        round(sum(r.cost_usd for r in records), 6),
        len(records),
        sum(r.turns for r in records),
    )


async def run_arm(arm: str, model: str, timeout: float) -> Run:
    workspace = Path(tempfile.mkdtemp(prefix=f"opa-fanout-{arm}-")) / "platform"
    build(workspace)
    server = build_server(make_config(workspace))
    runtime = server._opa_runtime
    try:
        started = time.monotonic()
        if arm == "fanout":
            # One child per subsystem, scoped so no file is read twice.
            for subsystem, role in SUBSYSTEMS.items():
                prompt = DIMENSION_PROMPT.format(subsystem=subsystem, role=role)
                await call(
                    server,
                    f"await rlm({prompt!r}, name={subsystem!r}, model={model!r})",
                )
            await wait_for_inbox(runtime, len(SUBSYSTEMS), timeout)
        else:
            await call(
                server, f"await rlm({WHOLE_PROMPT!r}, name='reviewer', model={model!r})"
            )
            await wait_for_inbox(runtime, 1, timeout)
        elapsed = int((time.monotonic() - started) * 1000)

        messages = runtime.rlm.mailbox.read()
        combined = "\n\n".join(m["message"] for m in messages)
        tokens, cost, children, turns = registry_totals(runtime)
        return Run(
            arm=arm,
            child_tokens=tokens,
            child_cost=cost,
            children=children,
            child_turns=turns,
            duration_ms=elapsed,
            found=grade(combined),
            answers={m["sender"]: m["message"][:300] for m in messages},
            ok=all(m.get("ok") for m in messages) and turns == len(messages),
        )
    finally:
        await runtime.shutdown()
        shutil.rmtree(workspace.parent, ignore_errors=True)


async def main_async(args) -> None:
    probe = Path(tempfile.mkdtemp()) / "platform"
    build(probe)
    print(
        f"corpus: {len(list(probe.rglob('*.py')))} files, "
        f"~{approximate_tokens(probe):,} tokens, {len(SUBSYSTEMS)} subsystems"
    )
    shutil.rmtree(probe.parent, ignore_errors=True)

    rows: list[Run] = []
    for attempt in range(args.repeat):
        for arm in ("single", "fanout"):
            print(f"[{arm}] attempt {attempt + 1}/{args.repeat} …", flush=True)
            row = await run_arm(arm, args.model, args.timeout)
            print(
                f"    child_tokens={row.child_tokens:,} cost=${row.total_cost} "
                f"{row.duration_ms:,}ms found={sorted(row.found)} ok={row.ok}",
                flush=True,
            )
            rows.append(row)

    out = Path(args.out) / f"fanout-{args.model}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    out.write_text(
        json.dumps(
            previous
            + [
                asdict(r) | {"total_tokens": r.total_tokens, "total_cost": r.total_cost,
                             "found_count": len(r.found)}
                for r in rows
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--out", default=str(Path(__file__).parent / "results"))
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
