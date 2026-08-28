"""Autonomous - keep re-tasking a child until a gate passes.

This is the one layer that really runs on its own. Everywhere else we are a
guest in someone's turn loop and can only leave things to be collected; here opa
owns the child processes, so it can act without the host being present.

Stop conditions: max turns, token budget, wall-clock timeout. When the quality
gate fails, **its output is fed back in as the next prompt** - that feedback is
the difference between this and a cron job that reruns a script.

WARNING: this edits files and runs commands unsupervised, including the gate
command itself. Do not use it outside a devcontainer or VM (docs/security.md).
"""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_GATE_OUTPUT = 4000
WORKTREE_TIMEOUT = 30

NO_CHANGE_PROMPT = """\
You did not change any file on that attempt, so the gate `{gate}` failed exactly
as before - rerunning it would produce the same output again.

Stop re-reading and edit something. If you believe the code is already correct,
say so and explain what you think the gate is actually checking, rather than
trying again unchanged.

Gate output:
{output}"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class GateResult:
    passed: bool
    returncode: int
    output: str


@dataclass
class TurnRecord:
    index: int
    prompt_preview: str
    child_ok: bool
    gate_passed: bool | None
    tokens: int
    changed_files: bool | None = None
    at: str = field(default_factory=_now)


@dataclass
class RunResult:
    objective: str
    child_name: str
    outcome: str            # gate_passed | max_turns | token_budget | timeout | error
    turns: list[TurnRecord] = field(default_factory=list)
    tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {"turn_count": len(self.turns)}


def _run_gate_blocking(command: str, cwd: Path, timeout: float) -> GateResult:
    try:
        proc = subprocess.run(
            command, shell=True, cwd=str(cwd), capture_output=True,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return GateResult(False, -1, f"gate timed out after {timeout}s")
    output = (proc.stdout + proc.stderr).decode(errors="replace")
    if len(output) > MAX_GATE_OUTPUT:
        head = MAX_GATE_OUTPUT * 2 // 5
        output = output[:head] + "\n… [gate output truncated] …\n" + output[-(MAX_GATE_OUTPUT - head):]
    return GateResult(proc.returncode == 0, proc.returncode, output)


def worktree_fingerprint(cwd: Path) -> str | None:
    """A hash of the working tree, or None outside a git repository.

    Used to notice that a turn changed nothing. Re-running a gate against an
    identical tree cannot produce a different result, so spending another child
    turn on it is pure waste - the child needs telling that it edited nothing,
    not another copy of the same failure.

    Covers tracked changes and untracked file contents, so creating a file
    counts as a change.
    """
    def git(*args: str) -> bytes | None:
        try:
            proc = subprocess.run(
                ["git", *args], cwd=str(cwd), capture_output=True,
                timeout=WORKTREE_TIMEOUT, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return proc.stdout if proc.returncode == 0 else None

    if git("rev-parse", "--is-inside-work-tree") is None:
        return None

    digest = hashlib.sha256()
    for args in (("status", "--porcelain=v1"), ("diff", "--binary", "HEAD")):
        digest.update(git(*args) or b"")
    untracked = (git("ls-files", "--others", "--exclude-standard") or b"").split()
    for relative in sorted(untracked):
        path = cwd / relative.decode(errors="replace")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
    return digest.hexdigest()


async def run_gate(command: str, cwd: Path, timeout: float = 600) -> GateResult:
    """Run the quality gate. A non-zero exit means "not done yet".

    Off the event loop: a gate is usually a test suite, and running it inline
    would freeze the bridge and every other child callback for its whole
    duration.
    """
    return await asyncio.to_thread(_run_gate_blocking, command, cwd, timeout)


class AutonomousRunner:
    """Drives one child until the gate passes or a budget runs out."""

    def __init__(self, rlm_service, goal_store=None) -> None:
        self.rlm = rlm_service
        self.goals = goal_store
        self.active: RunResult | None = None

    async def start(
        self,
        objective: str,
        *,
        child_name: str,
        gate: str | None = None,
        max_turns: int = 5,
        token_budget: int | None = None,
        wall_clock_seconds: float | None = None,
        model: str | None = None,
        turn_timeout: float = 1800,
    ) -> dict[str, Any]:
        if not isinstance(objective, str) or not objective.strip():
            raise ValueError("objective must be a non-empty string")
        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        if self.active is not None:
            raise RuntimeError("an autonomous run is already in progress")

        result = RunResult(objective=objective.strip(), child_name=child_name, outcome="error")
        self.active = result
        started = time.monotonic()
        cwd = self.rlm.config.workspace
        prompt = objective.strip()
        fingerprint = await asyncio.to_thread(worktree_fingerprint, cwd)

        try:
            for index in range(1, max_turns + 1):
                if wall_clock_seconds and time.monotonic() - started > wall_clock_seconds:
                    result.outcome = "timeout"
                    result.detail = f"wall clock exceeded {wall_clock_seconds}s"
                    break
                if token_budget and result.tokens >= token_budget:
                    result.outcome = "token_budget"
                    result.detail = f"token budget of {token_budget} exhausted"
                    break

                turn = await self._one_turn(
                    prompt, child_name, index, model=model, timeout=turn_timeout
                )
                result.turns.append(turn)
                record = self.rlm.registry.get(child_name)
                if record is not None:
                    result.tokens = record.tokens
                    result.cost_usd = record.cost_usd
                    if self.goals is not None:
                        self.goals.spend(turn.tokens)

                if not turn.child_ok:
                    result.outcome = "error"
                    result.detail = (record.last_error if record else "child failed") or "child failed"
                    break
                if gate is None:
                    result.outcome = "gate_passed"
                    result.detail = "no gate was configured; stopped after one turn"
                    break

                after = await asyncio.to_thread(worktree_fingerprint, cwd)
                turn.changed_files = None if after is None else after != fingerprint
                unchanged = fingerprint is not None and after == fingerprint
                fingerprint = after

                gate_result = await run_gate(gate, cwd)
                turn.gate_passed = gate_result.passed
                if gate_result.passed:
                    result.outcome = "gate_passed"
                    result.detail = f"`{gate}` exited 0"
                    break

                # The gate's own output becomes the next instruction - except when
                # the tree is untouched, where repeating it invites the same
                # no-op again.
                prompt = (
                    NO_CHANGE_PROMPT.format(gate=gate, output=gate_result.output)
                    if unchanged
                    else (
                        f"The quality gate `{gate}` still fails. Fix the cause and "
                        f"try again.\n\nGate output:\n{gate_result.output}"
                    )
                )
            else:
                result.outcome = "max_turns"
                result.detail = f"stopped after {max_turns} turns without passing the gate"
        finally:
            result.duration_ms = int((time.monotonic() - started) * 1000)
            self.active = None
        return result.as_dict()

    async def _one_turn(
        self, prompt: str, child_name: str, index: int, *, model: str | None, timeout: float
    ) -> TurnRecord:
        record = self.rlm.registry.get(child_name)
        before = record.tokens if record else 0
        before_turns = record.turns if record else 0

        if record is None:
            await self.rlm.run(prompt, name=child_name, model=model)
        else:
            await self.rlm.send(prompt, receiver_name=child_name)

        deadline = time.monotonic() + timeout
        while True:
            record = self.rlm.registry.get(child_name)
            if record is not None and record.turns > before_turns:
                break
            if time.monotonic() > deadline:
                return TurnRecord(index, prompt[:120], False, None, 0)
            await asyncio.sleep(1)

        return TurnRecord(
            index=index,
            prompt_preview=prompt[:120],
            child_ok=record.status != "error",
            gate_passed=None,
            tokens=record.tokens - before,
        )

    def status(self) -> dict[str, Any]:
        return {"running": self.active is not None} | (
            self.active.as_dict() if self.active else {}
        )
