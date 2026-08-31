"""AgentAdapter - the contract every backend must satisfy.

A backend qualifies if it can do exactly two things:
  1. run non-interactively from a single prompt, and
  2. **resume by session id** - where child persistence comes from.

Both claude and codex were measured to satisfy it (ARCHITECTURE section 5.1).

The session id comes from different places per backend:
  - claude : we issue the UUID and pass it as `--session-id`
  - codex  : codex issues it and we read it back from the first turn
So `preassign_session_id()` may return None, and the real id surfaces through
`TurnResult.session_id`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class TurnRequest:
    prompt: str
    cwd: Path
    session_dir: Path
    session_id: str | None = None      # None means the backend issues it
    resume: bool = False
    model: str | None = None
    system_prompt: str | None = None
    permission_mode: str = "acceptEdits"
    allowed_tools: tuple[str, ...] = ()
    allow_dangerous: bool = False
    child_name: str | None = None       # used for the child -> parent push channel
    can_message_parent: bool = False
    host_socket: str | None = None      # the child cannot reach the parent without it
    token: str | None = None            # what the bridge will recognise it as
    timeout: float = 1800.0


@dataclass(frozen=True)
class TurnResult:
    ok: bool
    text: str
    session_id: str | None = None
    tokens: int | None = None
    cost_usd: float | None = None
    raw_path: Path | None = None       # raw backend output (the full event stream)
    error: str | None = None
    duration_ms: int = 0


class AgentAdapter(Protocol):
    name: str

    def available(self) -> bool:
        """Is the CLI on PATH and runnable?"""
        ...

    def preassign_session_id(self) -> str | None:
        """Return an id we choose, or None if the backend issues its own."""
        ...

    async def run(self, request: TurnRequest) -> TurnResult:
        """Run one turn. With `resume=True` the earlier context carries over."""
        ...
