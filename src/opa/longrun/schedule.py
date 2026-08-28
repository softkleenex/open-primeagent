"""Scheduled prompts and heartbeats.

We do not own the host's turn loop, so nothing here can wake an agent. Due items
are **collected on the next turn** through `opa_status()` or
`schedule.due()` — a pull, not a push. Saying otherwise would be a lie the first
time someone left a terminal idle.

The one place a schedule really fires on its own is `autonomous`, where opa
drives the children itself and can therefore act without the host.

`source` separates what the user asked for from what the agent scheduled itself
(upstream keeps `/heartbeat` and `rlm_heartbeat` apart for the same reason): a
user can always see, and clear, what the agent set up on its own.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from ..session import jsonl

Kind = Literal["once", "interval"]
Source = Literal["user", "agent"]


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


@dataclass
class Entry:
    id: str
    prompt: str
    kind: Kind
    source: Source
    due_at: str
    interval_seconds: int | None = None
    created_at: str = field(default_factory=lambda: _iso(_now()))
    last_fired_at: str | None = None
    fires: int = 0
    active: bool = True


class ScheduleStore:
    """A tiny durable queue of prompts that become due at a time."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: dict[str, Entry] = {}
        self.load()

    def load(self) -> ScheduleStore:
        self.entries = {}
        for record in jsonl.read(self.path):
            known = {f for f in Entry.__dataclass_fields__}
            try:
                entry = Entry(**{k: v for k, v in record.items() if k in known})
            except TypeError:
                continue  # one bad line must not hide the rest
            self.entries[entry.id] = entry
        return self

    def _rewrite(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        for entry in self.entries.values():
            jsonl.append(self.path, asdict(entry))

    # ---------- API ----------

    def create(
        self,
        prompt: str,
        *,
        in_seconds: int | None = None,
        at: str | None = None,
        every_seconds: int | None = None,
        source: Source = "agent",
    ) -> Entry:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if sum(x is not None for x in (in_seconds, at, every_seconds)) != 1:
            raise ValueError("pass exactly one of in_seconds, at, every_seconds")

        if every_seconds is not None:
            if not isinstance(every_seconds, int) or every_seconds < 30:
                raise ValueError("every_seconds must be an integer of at least 30")
            kind: Kind = "interval"
            due = _now() + timedelta(seconds=every_seconds)
        elif in_seconds is not None:
            if not isinstance(in_seconds, int) or in_seconds < 0:
                raise ValueError("in_seconds must be a non-negative integer")
            kind = "once"
            due = _now() + timedelta(seconds=in_seconds)
        else:
            try:
                parsed = datetime.fromisoformat(str(at))
            except ValueError as exc:
                raise ValueError(f"at must be an ISO-8601 timestamp, got {at!r}") from exc
            due = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            kind = "once"

        entry = Entry(
            id=f"sch-{uuid.uuid4().hex[:8]}",
            prompt=prompt.strip(),
            kind=kind,
            source=source,
            due_at=_iso(due),
            interval_seconds=every_seconds,
        )
        self.entries[entry.id] = entry
        jsonl.append(self.path, asdict(entry))
        return entry

    def list(self, *, source: Source | None = None) -> list[Entry]:
        entries = [e for e in self.entries.values() if source is None or e.source == source]
        return sorted(entries, key=lambda e: e.due_at)

    def delete(self, entry_id: str) -> Entry:
        entry = self.entries.pop(entry_id, None)
        if entry is None:
            known = ", ".join(self.entries) or "(none)"
            raise KeyError(f"no schedule entry {entry_id!r}. known: {known}")
        self._rewrite()
        return entry

    def due(self, *, collect: bool = True) -> list[Entry]:
        """Entries whose time has passed.

        `collect=True` marks them fired: a one-off deactivates, an interval is
        pushed to its next slot. Pass False to look without consuming.
        """
        now = _now()
        ready = [
            entry
            for entry in self.list()
            if entry.active and datetime.fromisoformat(entry.due_at) <= now
        ]
        if not ready or not collect:
            return ready
        for entry in ready:
            entry.fires += 1
            entry.last_fired_at = _iso(now)
            if entry.kind == "interval" and entry.interval_seconds:
                entry.due_at = _iso(now + timedelta(seconds=entry.interval_seconds))
            else:
                entry.active = False
        self._rewrite()
        return ready
