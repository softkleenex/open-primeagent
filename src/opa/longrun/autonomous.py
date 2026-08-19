"""Autonomous - keep running the next turn until a gate passes.

Stop conditions: max turns, token budget, wall-clock timeout.
When the quality gate fails, **its output is fed back in as the next input** -
that is the difference from a cron-driven AI script.

WARNING: this mode edits files and runs commands unsupervised. Do not use it
outside a devcontainer or VM (docs/security.md).
"""

from __future__ import annotations


class AutonomousRun:
    async def start(self, *, max_turns: int, token_budget: int | None,
                    wall_clock_seconds: int | None, gate: str | None) -> dict: ...
    async def stop(self) -> dict: ...
