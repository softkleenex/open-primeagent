"""Benchmark runner: the same multi-turn task, with and without open-primeagent.

What is measured
----------------
Both arms get the identical task, model and corpus. The only differences are
that the `opa` arm has the opa MCP server attached and a CLAUDE.md carrying the
one instruction the product's own projection writes.

The task is deliberately **multi-turn**. A single-shot question is not
interesting: any competent agent can already shell out and compute. The cost
shows up when a later turn depends on an earlier turn's intermediate data --
the baseline must carry it in context or recompute it, while opa keeps it in a
Python variable.

Usage:
    uv run python bench/run.py --model sonnet --repeat 1
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from corpus import build

REPO = Path(__file__).resolve().parent.parent

TURNS = [
    (
        "In the corpus/ directory, how many .py files contain at least one "
        "'# TODO' marker? Reply with only the number."
    ),
    (
        "Of exactly those files, how many also contain the line 'import os'? "
        "Reply with only the number."
    ),
    (
        "Among exactly those files, list the 3 with the most lines, most lines "
        "first. Reply with only the three filenames, comma separated."
    ),
]

# The single line open-primeagent's own projection writes into CLAUDE.md.
OPA_GUIDANCE = """\
<!-- opa:begin — generated. Nothing outside this block is touched. -->
## open-primeagent

### Rules for this project

- **Use opa_python for data work** — run analysis in the persistent kernel and
  keep intermediate results (file lists, counts, sets) in Python variables
  across turns. Print only what you need to answer.
<!-- opa:end -->
"""


@dataclass
class TurnMetrics:
    turn: int
    answer: str
    input_tokens: int
    output_tokens: int
    cache_read: int
    cache_write: int
    cost_usd: float
    num_turns: int
    duration_ms: int


@dataclass
class RunMetrics:
    arm: str
    model: str
    turns: list[TurnMetrics]
    correct: list[bool]

    @property
    def totals(self) -> dict:
        return {
            "input_tokens": sum(t.input_tokens for t in self.turns),
            "output_tokens": sum(t.output_tokens for t in self.turns),
            "cache_read": sum(t.cache_read for t in self.turns),
            "cache_write": sum(t.cache_write for t in self.turns),
            "billed_tokens": sum(
                t.input_tokens + t.output_tokens + t.cache_write for t in self.turns
            ),
            "cost_usd": round(sum(t.cost_usd for t in self.turns), 6),
            "agent_turns": sum(t.num_turns for t in self.turns),
            "duration_ms": sum(t.duration_ms for t in self.turns),
            "correct": sum(self.correct),
        }


def write_mcp_config(workspace: Path) -> Path:
    config = {
        "mcpServers": {
            "opa": {
                "command": "uv",
                "args": ["run", "--directory", str(REPO), "opa"],
                "env": {
                    "OPA_WORKSPACE": str(workspace),
                    "OPA_ROOT": str(workspace / ".opa"),
                    "OPA_GLOBAL_ROOT": str(workspace / ".opa-global"),
                },
            }
        }
    }
    path = workspace / "mcp.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def run_arm(arm: str, workspace: Path, model: str, timeout: float) -> RunMetrics:
    session_id = str(uuid.uuid4())
    turns: list[TurnMetrics] = []

    for index, prompt in enumerate(TURNS):
        cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", model]
        cmd += ["--session-id", session_id] if index == 0 else ["--resume", session_id]
        if arm == "opa":
            cmd += ["--mcp-config", str(workspace / "mcp.json")]
            cmd += ["--allowedTools", "mcp__opa__opa_python,Bash,Read,Grep,Glob"]
        else:
            cmd += ["--allowedTools", "Bash,Read,Grep,Glob"]

        started = time.monotonic()
        proc = subprocess.run(
            cmd,
            cwd=workspace,
            capture_output=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        elapsed = int((time.monotonic() - started) * 1000)
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = {"result": f"<parse error: {proc.stderr.decode()[:200]}>", "usage": {}}

        usage = payload.get("usage") or {}
        turns.append(
            TurnMetrics(
                turn=index + 1,
                answer=(payload.get("result") or "").strip(),
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
                cache_read=int(usage.get("cache_read_input_tokens", 0)),
                cache_write=int(usage.get("cache_creation_input_tokens", 0)),
                cost_usd=float(payload.get("total_cost_usd") or 0.0),
                num_turns=int(payload.get("num_turns") or 0),
                duration_ms=elapsed,
            )
        )
        print(f"    turn {index + 1}: {turns[-1].answer[:70]!r}  ({elapsed}ms)")

    return RunMetrics(arm=arm, model=model, turns=turns, correct=[])


def grade(metrics: RunMetrics, truth) -> RunMetrics:
    answers = [t.answer for t in metrics.turns]
    correct = [
        str(truth.files_with_todo) in answers[0],
        str(truth.todo_and_os) in answers[1],
        all(name in answers[2] for name in truth.top3_by_lines),
    ]
    metrics.correct = correct
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--arms", default="baseline,opa")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--out", default=str(Path(__file__).parent / "results"))
    args = parser.parse_args()

    results = []
    for attempt in range(args.repeat):
      for arm in args.arms.split(","):
        workspace = Path(
            __import__("tempfile").mkdtemp(prefix=f"opa-bench-{arm}-")
        )
        truth = build(workspace / "corpus")
        if arm == "opa":
            write_mcp_config(workspace)
            (workspace / "CLAUDE.md").write_text(OPA_GUIDANCE, encoding="utf-8")

        print(f"[{arm}] attempt {attempt + 1}/{args.repeat} workspace={workspace}")
        metrics = grade(run_arm(arm, workspace, args.model, args.timeout), truth)
        print(f"[{arm}] totals: {metrics.totals}\n")
        results.append(asdict(metrics) | {"totals": metrics.totals, "truth": asdict(truth)})

    out = Path(args.out) / f"multiturn-{args.model}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    out.write_text(json.dumps(previous + results, indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
