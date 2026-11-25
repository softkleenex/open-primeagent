"""ChildRegistry - what makes a child not disposable.

After a kernel restart, a context compaction or a host restart,
`await rlm.list_subagents()` must still return the same children. That is why
the registry lives on disk rather than in kernel memory.

Layout:
    children/
      index.json                 name -> rlm_child_id
      <rlm_child_id>/child.json  ChildRecord
      <rlm_child_id>/turns.jsonl per-turn log
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from ..fsutil import atomic_write
from ..session import jsonl

ChildStatus = Literal["running", "completed", "error"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class ChildRecord:
    rlm_child_id: str
    name: str
    adapter: str
    cwd: str
    status: ChildStatus = "running"
    native_session_id: str | None = None
    model: str | None = None
    spec: str | None = None
    can_message_parent: bool = False
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    turns: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    last_error: str | None = None

    @classmethod
    def new(cls, name: str, adapter: str, cwd: Path, **kw) -> ChildRecord:
        return cls(
            rlm_child_id=f"opa-{uuid.uuid4().hex[:8]}",
            name=name,
            adapter=adapter,
            cwd=str(cwd),
            **kw,
        )


class ChildRegistry:
    def __init__(self, children_dir: Path) -> None:
        self.dir = children_dir
        self._records: dict[str, ChildRecord] = {}

    # ---------- persistence ----------

    def child_dir(self, rlm_child_id: str) -> Path:
        return self.dir / rlm_child_id

    def load(self) -> ChildRegistry:
        """Recover from disk. Must be called before anything else at server boot."""
        self._records.clear()
        if not self.dir.exists():
            return self
        for record_file in sorted(self.dir.glob("*/child.json")):
            # `delete` writes this marker and then unlinks child.json. Dying
            # between the two left the record on disk, and a child the user had
            # deleted came back on the next boot. The marker was written but
            # never read, so it looked like a tombstone without being one.
            if (record_file.parent / "deleted").exists():
                continue
            try:
                data = json.loads(record_file.read_text(encoding="utf-8"))
                record = ChildRecord(**data)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue  # one corrupt record must not hide the other children
            self._records[record.rlm_child_id] = record

        # A turn cannot outlive the process that awaited it. Anything still
        # marked running was interrupted - the server was killed or crashed
        # mid-turn - and nothing will ever come back to finish it, because the
        # task that would have run the `finally` died with it.
        #
        # Left alone, that record claims work is in flight forever: `attention`
        # says "still working" and tells you to wait for a report that cannot
        # arrive, and `list_subagents` reports a live `active_session_id`. The
        # child itself is still resumable - its session id is intact - so this
        # only corrects the claim about a turn, not the child's usefulness.
        for record in self._records.values():
            if record.status == "running":
                record.status = "error"
                record.last_error = (
                    "interrupted: the server stopped while this turn was in flight. "
                    "The session is intact, so the child can still be re-tasked."
                )
                self._persist(record)
        return self

    def _persist(self, record: ChildRecord) -> None:
        """Write atomically. A half-written child.json is a child nothing can find."""
        directory = self.child_dir(record.rlm_child_id)
        directory.mkdir(parents=True, exist_ok=True)
        atomic_write(
            directory / "child.json", json.dumps(asdict(record), indent=2, ensure_ascii=False)
        )

    # ---------- CRUD ----------

    def add(self, record: ChildRecord) -> ChildRecord:
        if self.get(record.name) is not None:
            raise ValueError(
                f"a sub-agent named {record.name!r} already exists. "
                f"Send it a message instead of creating a duplicate."
            )
        # Persist first. Registering a child whose record never reached disk
        # would hand back a handle for something no restart could ever recover.
        self._persist(record)
        self._records[record.rlm_child_id] = record
        return record

    def update(self, rlm_child_id: str, **changes) -> ChildRecord:
        record = self._records[rlm_child_id]
        for key, value in changes.items():
            setattr(record, key, value)
        record.updated_at = _now()
        self._persist(record)
        return record

    def get(self, selector: str) -> ChildRecord | None:
        """Look up by rlm_child_id or by name."""
        if selector in self._records:
            return self._records[selector]
        for record in self._records.values():
            if record.name == selector:
                return record
        return None

    def list(self) -> list[ChildRecord]:
        return sorted(self._records.values(), key=lambda r: r.created_at)

    def delete(self, selector: str) -> ChildRecord:
        """Only ever deleted on request. Nothing is reaped automatically - residency is the default."""
        record = self.get(selector)
        if record is None:
            known = ", ".join(r.name for r in self.list()) or "(none)"
            raise KeyError(f"no sub-agent matches {selector!r}. known: {known}")
        del self._records[record.rlm_child_id]
        directory = self.child_dir(record.rlm_child_id)
        if directory.exists():
            (directory / "deleted").write_text(_now(), encoding="utf-8")
            (directory / "child.json").unlink(missing_ok=True)
        return record

    # ---------- turn log ----------

    def record_turn(self, rlm_child_id: str, entry: dict) -> None:
        jsonl.append(self.child_dir(rlm_child_id) / "turns.jsonl", {"at": _now(), **entry})

    def turns(self, rlm_child_id: str, *, limit: int | None = None) -> list[dict]:
        path = self.child_dir(rlm_child_id) / "turns.jsonl"
        records = list(jsonl.read(path))
        return records[-limit:] if limit else records

    def reuse(self) -> dict:
        """What keeping sub-agents saved, estimated - and how it was estimated.

        The baseline is each child's own first turn: what a cold child cost, on
        this machine, for this codebase. Every successful follow-up is credited
        with the difference between that and what the follow-up actually cost,
        and never with less than zero. It is an estimate - a fresh child asked
        the follow-up would not have cost exactly the first turn - so the
        result says so in `basis` rather than presenting a measurement.
        """
        children = follow_ups = tokens_saved = 0
        cost_saved = 0.0
        for record in self.list():
            turns = [t for t in self.turns(record.rlm_child_id) if t.get("ok")]
            cold = next(
                (t for t in turns if not t.get("resume") and t.get("tokens") is not None), None
            )
            warm = [t for t in turns if t.get("resume") and t.get("tokens") is not None]
            if cold is None or not warm:
                continue
            children += 1
            follow_ups += len(warm)
            for turn in warm:
                tokens_saved += max(0, int(cold["tokens"]) - int(turn["tokens"]))
                if cold.get("cost_usd") is not None and turn.get("cost_usd") is not None:
                    cost_saved += max(0.0, float(cold["cost_usd"]) - float(turn["cost_usd"]))
        receipt = None
        if follow_ups:
            money = f", ~${cost_saved:.2f} at API rates" if cost_saved >= 0.01 else ""
            receipt = (
                f"open-primeagent: {follow_ups} follow-up(s) to {children} warm sub-agent(s), "
                f"~{tokens_saved:,} tokens not re-spent{money} "
                "(estimated against each sub-agent's own first turn)"
            )
        return {
            "warm_children": children,
            "follow_ups": follow_ups,
            "estimated_tokens_saved": tokens_saved,
            "estimated_cost_saved_usd": round(cost_saved, 4),
            "basis": "each follow-up vs. that sub-agent's own first (cold) turn; an estimate",
            "receipt": receipt,
        }
