"""Sub-agent benchmarks: parallel specialists, and a warm child versus a cold one.

This is the part of open-primeagent that has no equivalent in a plain coding
agent, and until now it was the only claim with no measurement behind it.

**Child tokens are counted.** The parent's `usage` only reports the parent, so
reading it alone would make opa look free. We add up every child's tokens and
cost from the registry and report the total.

    uv run python bench/subagents.py --experiment parallel --repeat 3
    uv run python bench/subagents.py --experiment warm --repeat 3
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from project import build

REPO = Path(__file__).resolve().parent.parent

DIMENSIONS = ["security", "test coverage", "performance", "API consistency"]

REVIEW_TASK = (
    "Review this service across four dimensions: security, test coverage, "
    "performance, and API consistency. Report the single most important concrete "
    "finding for each dimension, naming the file. Be specific: name the actual "
    "problem, not the category."
)

# What a review must mention for us to count a dimension as found. Crude on
# purpose: keyword matching is transparent and reproducible, unlike judging prose.
MARKERS = {
    "security": ["hardcoded", "sk-live", "admin_token", "sql injection", "concatenat"],
    "tests": ["invoice"],
    "performance": ["quadratic", "o(n^2)", "o(n*m)", "o(n2)", "nested loop", "aggregate"],
    "api": ["inconsistent", "error shape", "error format", "different shapes", "routes.py"],
}

OPA_GUIDANCE = """\
<!-- opa:begin — generated. Nothing outside this block is touched. -->
## open-primeagent

### Rules for this project

- **Use opa_python and fan out with rlm()** for multi-dimension review work.
  Spawn one named sub-agent per dimension, then poll `agent_message.inbox()`
  until every one has reported, and summarise from those reports.
  `rlm()` returns immediately; the children run in parallel.
<!-- opa:end -->
"""

WARM_SETUP = (
    "Have a sub-agent named 'auth-reviewer' read api/auth.py closely and report "
    "every problem it finds. Wait for its report, then reply with only READY."
)
WARM_FOLLOWUP = (
    "Ask the existing sub-agent named 'auth-reviewer' this follow-up: 'Of the "
    "problems you found, which one would you fix first, and what exactly would "
    "the fixed code look like?' Wait for its answer and reply with it verbatim."
)
COLD_FOLLOWUP = (
    "Create a sub-agent named 'auth-reviewer-2' and ask it: 'Read api/auth.py. "
    "Of the problems in it, which one would you fix first, and what exactly "
    "would the fixed code look like?' Wait for its answer and reply with it "
    "verbatim."
)


@dataclass
class Usage:
    parent_tokens: int = 0
    parent_cost: float = 0.0
    child_tokens: int = 0
    child_cost: float = 0.0
    children: int = 0
    agent_turns: int = 0
    duration_ms: int = 0
    found: list[str] = field(default_factory=list)
    answer: str = ""

    @property
    def total_tokens(self) -> int:
        return self.parent_tokens + self.child_tokens

    @property
    def total_cost(self) -> float:
        return round(self.parent_cost + self.child_cost, 6)


def write_mcp_config(workspace: Path) -> None:
    (workspace / "mcp.json").write_text(
        json.dumps(
            {
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
        ),
        encoding="utf-8",
    )


def child_usage(workspace: Path) -> tuple[int, float, int]:
    """Sum every child's tokens and cost. Ignoring these would flatter opa."""
    tokens = cost = 0.0
    count = 0
    for record in (workspace / ".opa").rglob("children/*/child.json"):
        try:
            data = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tokens += data.get("tokens") or 0
        cost += data.get("cost_usd") or 0.0
        count += 1
    return int(tokens), round(cost, 6), count


def grade(text: str) -> list[str]:
    lowered = text.lower()
    return [
        dimension
        for dimension, markers in MARKERS.items()
        if any(marker in lowered for marker in markers)
    ]


def claude(
    prompt: str, workspace: Path, model: str, timeout: float, *, opa: bool,
    session_id: str | None = None, resume: bool = False,
) -> tuple[dict, int]:
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", model]
    if session_id:
        cmd += (["--resume", session_id] if resume else ["--session-id", session_id])
    if opa:
        cmd += ["--mcp-config", str(workspace / "mcp.json")]
        cmd += ["--allowedTools", "mcp__opa__opa_python,Bash,Read,Grep,Glob"]
    else:
        cmd += ["--allowedTools", "Bash,Read,Grep,Glob,Task"]
    started = time.monotonic()
    proc = subprocess.run(
        cmd, cwd=workspace, capture_output=True, timeout=timeout,
        stdin=subprocess.DEVNULL, check=False,
    )
    elapsed = int((time.monotonic() - started) * 1000)
    try:
        return json.loads(proc.stdout), elapsed
    except json.JSONDecodeError:
        return {"result": f"<parse error: {proc.stderr.decode()[:300]}>", "usage": {}}, elapsed


def billed(payload: dict) -> int:
    usage = payload.get("usage") or {}
    return (
        int(usage.get("input_tokens", 0))
        + int(usage.get("output_tokens", 0))
        + int(usage.get("cache_creation_input_tokens", 0))
    )


def workspace_for(tag: str, *, opa: bool) -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"opa-sub-{tag}-")) / "svc"
    build(root)
    if opa:
        write_mcp_config(root)
        (root / "CLAUDE.md").write_text(OPA_GUIDANCE, encoding="utf-8")
    return root


# ---------- experiment 1: parallel specialists ----------

def run_parallel(arm: str, model: str, timeout: float) -> Usage:
    opa = arm == "opa"
    workspace = workspace_for(arm, opa=opa)
    payload, elapsed = claude(REVIEW_TASK, workspace, model, timeout, opa=opa)
    tokens, cost, count = child_usage(workspace) if opa else (0, 0.0, 0)
    answer = (payload.get("result") or "").strip()
    return Usage(
        parent_tokens=billed(payload),
        parent_cost=float(payload.get("total_cost_usd") or 0.0),
        child_tokens=tokens,
        child_cost=cost,
        children=count,
        agent_turns=int(payload.get("num_turns") or 0),
        duration_ms=elapsed,
        found=grade(answer),
        answer=answer[:400],
    )


# ---------- experiment 2: warm child vs cold child ----------

def run_warm(arm: str, model: str, timeout: float) -> Usage:
    """Both arms pay for the setup; only the follow-up turn is measured."""
    workspace = workspace_for(arm, opa=True)
    session_id = str(uuid.uuid4())

    claude(WARM_SETUP, workspace, model, timeout, opa=True, session_id=session_id)
    before_tokens, before_cost, _ = child_usage(workspace)

    prompt = WARM_FOLLOWUP if arm == "warm" else COLD_FOLLOWUP
    payload, elapsed = claude(
        prompt, workspace, model, timeout, opa=True, session_id=session_id, resume=True
    )
    after_tokens, after_cost, count = child_usage(workspace)
    answer = (payload.get("result") or "").strip()
    return Usage(
        parent_tokens=billed(payload),
        parent_cost=float(payload.get("total_cost_usd") or 0.0),
        child_tokens=after_tokens - before_tokens,
        child_cost=round(after_cost - before_cost, 6),
        children=count,
        agent_turns=int(payload.get("num_turns") or 0),
        duration_ms=elapsed,
        answer=answer[:400],
    )


EXPERIMENTS = {
    "parallel": (run_parallel, ["baseline", "opa"]),
    "warm": (run_warm, ["cold", "warm"]),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", default="parallel", choices=sorted(EXPERIMENTS))
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--out", default=str(Path(__file__).parent / "results"))
    args = parser.parse_args()

    runner, arms = EXPERIMENTS[args.experiment]
    rows = []
    for attempt in range(args.repeat):
        for arm in arms:
            print(f"[{arm}] attempt {attempt + 1}/{args.repeat} …")
            usage = runner(arm, args.model, args.timeout)
            print(
                f"    parent={usage.parent_tokens} child={usage.child_tokens} "
                f"total={usage.total_tokens} cost=${usage.total_cost} "
                f"children={usage.children} turns={usage.agent_turns} "
                f"found={usage.found} ({usage.duration_ms}ms)"
            )
            rows.append(
                asdict(usage)
                | {"arm": arm, "total_tokens": usage.total_tokens,
                   "total_cost": usage.total_cost, "found_count": len(usage.found)}
            )

    out = Path(args.out) / f"subagents-{args.experiment}-{args.model}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    out.write_text(json.dumps(previous + rows, indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
