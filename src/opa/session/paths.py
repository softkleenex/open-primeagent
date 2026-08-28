"""Session directory layout.

    .opa/
    └── sessions/<session_id>/
        ├── session.json          session metadata
        ├── trajectory.jsonl      every host<->opa event (input to refinement)
        ├── outputs/<n>.txt       full output before truncation
        ├── goal.json             the session's persistent objective
        ├── goal.json
        ├── mailbox/<name>.jsonl
        └── children/
            ├── index.json        ChildRegistry
            └── <rlm_child_id>/
                ├── child.json
                └── turns.jsonl

Everything that must survive a kernel restart, a context compaction or a host
restart lives under here. The only thing held solely in kernel memory is the
user's own Python variables.

The harness is deliberately **not** here. It lives at `.opa/harness/` because it
is what the project taught us, not what one conversation did.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SessionPaths:
    root: Path
    session_id: str

    @property
    def dir(self) -> Path:
        return self.root / "sessions" / self.session_id

    @property
    def trajectory(self) -> Path:
        return self.dir / "trajectory.jsonl"

    @property
    def outputs(self) -> Path:
        return self.dir / "outputs"

    @property
    def goal(self) -> Path:
        return self.dir / "goal.json"

    @property
    def mailbox(self) -> Path:
        return self.dir / "mailbox"

    @property
    def children(self) -> Path:
        return self.dir / "children"

    @property
    def meta(self) -> Path:
        return self.dir / "session.json"

    def ensure(self) -> SessionPaths:
        """Create every directory this session needs."""
        for directory in (self.dir, self.outputs, self.mailbox, self.children):
            directory.mkdir(parents=True, exist_ok=True)
        return self
