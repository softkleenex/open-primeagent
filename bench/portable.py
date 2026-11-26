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
with every file tool disabled). opencode is not run here; that it reads
AGENTS.md is its documented behaviour, not our measurement.

`--teammate codex` closes that gap for Codex: the learning agent is still Claude
Code with open-primeagent, and the teammate and control arms are run by the
Codex CLI instead, with the user's config ignored (no MCP servers, no custom
provider). That is the case the README leads with: a rule Claude Code learned,
read by Codex. Codex reports no turn count, so for it `agent_turns` is the
number of actions it took (shell commands, file edits, tool calls).

The project is the `hard` variant from evolution.py: the generator that must
run after a schema edit is one of 16 scripts under tools/, and the failure does
not name it.

    uv run python bench/portable.py --repeat 6
    uv run python bench/portable.py --repeat 6 --variant deep
    uv run python bench/portable.py --repeat 6 --variant deep --teammate codex
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
    # Codex arms only: did it run the generator, or hand-edit the generated file?
    # The suite cannot tell the two apart; the rule in AGENTS.md says which is right.
    ran_generator: bool | None = None
    hand_edited_generated: bool | None = None
    commands: list[str] | None = None


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


HAND_WRITE = re.compile(r">\s*\S*models_gen\.py|(sed -i|perl -pi)[^|;&]*models_gen\.py")
CODEX_ACTIONS = {"command_execution", "file_change", "mcp_tool_call", "web_search"}


def _codex(cwd: Path, prompt: str, timeout: float):
    """Plain Codex CLI on this repo: the user's config ignored, so no MCP
    servers and no custom provider; only the repo's AGENTS.md can carry a rule."""
    cmd = ["codex", "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check"]
    cmd += ["-s", "workspace-write", "--json", "--", prompt]
    started = time.monotonic()
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, check=False
    )
    elapsed = int((time.monotonic() - started) * 1000)
    actions, billed, finished = 0, 0, False
    commands: list[str] = []
    edited: list[str] = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            event.get("type") == "item.completed"
            and (event.get("item") or {}).get("type") in CODEX_ACTIONS
        ):
            actions += 1
            item = event["item"]
            if item.get("type") == "command_execution":
                commands.append(str(item.get("command", ""))[:300])
            if item.get("type") == "file_change":
                edited += [str(c.get("path", "")) for c in item.get("changes") or []]
        if event.get("type") == "turn.completed":
            finished = True
            usage = event.get("usage") or {}
            billed += (
                int(usage.get("input_tokens", 0))
                - int(usage.get("cached_input_tokens", 0))
                + int(usage.get("output_tokens", 0))
            )
    if not finished:  # a usage limit or an auth error, not a result: stop the run
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[-2000:])
    return {"num_turns": actions, "commands": commands, "edited": edited}, elapsed, billed


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


# `deep`: the same repo, but three of the decoys are not inert. Each one really
# does write models_gen.py, in a shape that is plausible and wrong (sorted, with
# types, with a timestamp field the schema does not have), so running the wrong script
# looks like progress and the suite still fails. The rule is exactly as easy to
# state as before; it is much more expensive to rediscover. That is the case a
# recorded rule is for, and the `hard` result above is the case it is not.
WRONG_GENERATORS = {
    "make_models": "repr(sorted(schema.FIELDS))",
    "regen_types": "repr({f: 'str' for f in schema.FIELDS})",
    "sync_schema": "repr(list(schema.FIELDS) + ['created_at'])",
}
VARIANT = "hard"
TEAMMATE = "claude"


def _wrong_generator(expr: str) -> str:
    return (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent.parent))\n"
        "import schema\n"
        "root = Path(__file__).resolve().parent.parent\n"
        "(root / 'models_gen.py').write_text(\n"
        f"    'GENERATED_FIELDS = ' + {expr} + '\\n', encoding='utf-8'\n"
        ")\n"
        "print('regenerated models_gen.py')\n"
    )


def _fresh(prefix: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix=prefix)) / "svc"
    build_project(root, "hard")
    if VARIANT == "deep":
        for name, expr in WRONG_GENERATORS.items():
            (root / "tools" / f"{name}.py").write_text(_wrong_generator(expr), encoding="utf-8")
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
    extra = {}
    if TEAMMATE == "codex":
        payload, elapsed, billed = _codex(root, TASK, timeout)
        commands = payload["commands"]
        extra = {
            "ran_generator": any("sync_models" in c for c in commands),
            "hand_edited_generated": any(p.endswith("models_gen.py") for p in payload["edited"])
            or any(HAND_WRITE.search(c) for c in commands),
            "commands": commands,
        }
    else:
        payload, elapsed, billed = _claude(root, TASK, model, mcp_config=None, timeout=timeout)
    row = _row(arm, attempt, root, payload, elapsed, billed, **extra)
    shutil.rmtree(root.parent, ignore_errors=True)
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--variant", default="hard", choices=["hard", "deep"])
    parser.add_argument("--teammate", default="claude", choices=["claude", "codex"])
    parser.add_argument("--out", default=str(Path(__file__).parent / "results"))
    args = parser.parse_args()
    global VARIANT, TEAMMATE
    VARIANT = args.variant
    TEAMMATE = args.teammate

    stem = "portable" if args.variant == "hard" else f"portable-{args.variant}"
    if args.teammate != "claude":
        stem += f"-to-{args.teammate}"
    out = Path(args.out) / f"{stem}-{args.model}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []

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
                f"{row.duration_ms / 1000:.1f}s generator={row.ran_generator} "
                f"hand_edit={row.hand_edited_generated}",
                flush=True,
            )
            if agents_md is None:
                break  # nothing was learned, so there is no teammate arm to run
        # after every attempt, so a usage limit part-way loses no finished pair
        out.write_text(json.dumps(previous + [asdict(r) for r in rows], indent=2), encoding="utf-8")
        print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
