"""Does what one agent learned reach the next one through the repo alone?

The evolution benchmark hand-wrote the rule into CLAUDE.md. This one does not.
It runs the whole loop, with nothing staged between the steps:

    learn     Claude Code *with* open-primeagent does a task in a fresh repo
              whose one non-obvious rule it has to discover by failing, then is
              asked to save what a teammate's agent would need. Whatever it
              records is projected into AGENTS.md by opa_bootstrap.
    teammate  A fresh copy of the same repo, plus only that AGENTS.md - what a
              commit would carry. Plain Claude Code, *no* open-primeagent, no
              MCP servers at all, does the same task.
    control   The same fresh repo without the AGENTS.md.

AGENTS.md, not CLAUDE.md, on purpose: it is the file Codex and opencode read
too, so a rule that arrives this way arrives for them as well. Claude Code reads
it natively (checked: 2.1.332 quoted a line from an AGENTS.md-only directory
with every file tool disabled). We did not run Codex or opencode here; that
they read AGENTS.md is their documented behaviour, not our measurement.

The project is the `hard` variant from evolution.py: the generator that must
run after a schema edit is one of 16 scripts under tools/, and the failure does
not name it.

    uv run python bench/portable.py --repeat 3
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from evolution import TASK, build_project, tests_pass

REPO = Path(__file__).resolve().parent.parent
BEGIN = "<!-- opa:begin"
SAVE = (
    " After the tests pass, and before you reply, use open-primeagent to save what "
    "a teammate's coding agent would need to know about working in this repo, and "
    "project it into the repo's agent instruction files with opa_bootstrap."
)
TOOLS = "Bash,Read,Edit,Write,Grep,Glob"
OPA_TOOLS = "mcp__opa__opa_python,mcp__opa__opa_status,mcp__opa__opa_bootstrap"


@dataclass
class Run:
    arm: str
    attempt: int
    tests_pass: bool
    agent_turns: int
    duration_ms: int
    billed_tokens: int
    notional_cost_usd: float
    agents_md_has_block: bool | None = None
    block_names_generator: bool | None = None
    block_text: str = ""


def _claude(cwd: Path, prompt: str, model: str, *, mcp_config: Path | None, timeout: float):
    cmd = ["claude", "-p", "--output-format", "json", "--model", model]
    cmd += ["--permission-mode", "acceptEdits", "--strict-mcp-config"]
    allowed = TOOLS
    if mcp_config is not None:
        cmd += ["--mcp-config", str(mcp_config)]
        allowed += "," + OPA_TOOLS
    cmd += ["--allowedTools", allowed, "--", prompt]
    started = time.monotonic()
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, check=False
    )
    elapsed = int((time.monotonic() - started) * 1000)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {}
    usage = payload.get("usage") or {}
    billed = sum(
        int(usage.get(k, 0))
        for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens")
    )
    return payload, elapsed, billed


def _opa_config(workspace: Path) -> Path:
    """The opa server for this workspace only, with a private global store, so
    nothing learned in one run can leak into another through ~/.opa."""
    path = workspace.parent / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "opa": {
                        "command": sys.executable,
                        "args": ["-m", "opa.server"],
                        "env": {
                            "OPA_WORKSPACE": str(workspace),
                            "OPA_GLOBAL_ROOT": str(workspace.parent / "opa-global"),
                            "PYTHONPATH": os.pathsep.join(
                                [str(REPO / "src"), str(REPO / "runtime" / "src")]
                            ),
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def _fresh(prefix: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix=prefix)) / "svc"
    build_project(root, "hard")
    return root


def _row(arm, attempt, root, payload, elapsed, billed, **extra) -> Run:
    return Run(
        arm=arm,
        attempt=attempt,
        tests_pass=tests_pass(root),
        agent_turns=int(payload.get("num_turns") or 0),
        duration_ms=elapsed,
        billed_tokens=billed,
        notional_cost_usd=round(float(payload.get("total_cost_usd") or 0.0), 6),
        **extra,
    )


def learn(attempt: int, model: str, timeout: float) -> tuple[Run, str | None]:
    root = _fresh("opa-port-learn-")
    payload, elapsed, billed = _claude(
        root, TASK + SAVE, model, mcp_config=_opa_config(root), timeout=timeout
    )
    agents = root / "AGENTS.md"
    text = agents.read_text(encoding="utf-8") if agents.exists() else ""
    block = text[text.find(BEGIN) :] if BEGIN in text else ""
    row = _row(
        "learn",
        attempt,
        root,
        payload,
        elapsed,
        billed,
        agents_md_has_block=bool(block),
        block_names_generator="sync_models" in block,
        block_text=block[:2000],
    )
    shutil.rmtree(root.parent, ignore_errors=True)
    return row, (text or None)


def teammate(attempt: int, model: str, timeout: float, agents_md: str | None) -> Run:
    arm = "teammate" if agents_md is not None else "control"
    root = _fresh(f"opa-port-{arm}-")
    if agents_md is not None:
        (root / "AGENTS.md").write_text(agents_md, encoding="utf-8")
    payload, elapsed, billed = _claude(root, TASK, model, mcp_config=None, timeout=timeout)
    row = _row(arm, attempt, root, payload, elapsed, billed)
    shutil.rmtree(root.parent, ignore_errors=True)
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--out", default=str(Path(__file__).parent / "results"))
    args = parser.parse_args()

    rows: list[Run] = []
    for attempt in range(1, args.repeat + 1):
        learned, agents_md = learn(attempt, args.model, args.timeout)
        rows.append(learned)
        print(
            f"[learn {attempt}] pass={learned.tests_pass} turns={learned.agent_turns} "
            f"block={learned.agents_md_has_block} names_generator={learned.block_names_generator}",
            flush=True,
        )
        for agents in (agents_md, None):
            row = teammate(attempt, args.model, args.timeout, agents)
            rows.append(row)
            print(
                f"[{row.arm} {attempt}] pass={row.tests_pass} turns={row.agent_turns} "
                f"{row.duration_ms / 1000:.1f}s",
                flush=True,
            )
            if agents_md is None:
                break  # nothing was learned, so there is no teammate arm to run

    out = Path(args.out) / f"portable-{args.model}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    out.write_text(json.dumps(previous + [asdict(r) for r in rows], indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
