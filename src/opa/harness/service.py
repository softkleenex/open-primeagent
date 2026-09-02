"""HarnessService - joins the local and global scopes and applies refinements.

All CRUD for `H = (prompts, subagent specs, skills, memory)` lives here.

**Important**: this is not where the *judgement* happens. The host does not lend
us its model (Claude Code advertises no MCP `sampling` - measured, see
docs/evolution.md section 1.1). The caller decides - the host agent, or a refiner
child - and we gather the evidence, apply the delta, record it, and make it
reversible.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..session import jsonl
from .state import (
    KINDS,
    STATE_FILE_NAME,
    HarnessEntry,
    HarnessKind,
    HarnessScope,
    HarnessStore,
    RefinementEvent,
)

VALID_OPS = ("create", "update", "delete")


class HarnessService:
    def __init__(self, local_dir: Path, global_dir: Path) -> None:
        self.local = HarnessStore(local_dir / STATE_FILE_NAME, scope="local")
        self.global_ = HarnessStore(global_dir / STATE_FILE_NAME, scope="global")

    def store(self, global_: bool = False) -> HarnessStore:
        return self.global_ if global_ else self.local

    # ---------- CRUD (scope routing) ----------

    def create(self, kind: HarnessKind, title: str, content: str, *, global_=False, **kw):
        return self.store(global_).create(kind, title, content, **kw)

    def get(self, entry_id: str) -> HarnessEntry | None:
        entry_id, global_ = self._split_scope(entry_id)
        return self.store(global_).get(entry_id) or (
            None if global_ else self.global_.get(entry_id)
        )

    def update(self, entry_id: str, **changes) -> HarnessEntry:
        entry_id, global_ = self._split_scope(entry_id)
        store = self._owning_store(entry_id, global_)
        return store.update(entry_id, **changes)

    def delete(self, entry_id: str) -> HarnessEntry:
        entry_id, global_ = self._split_scope(entry_id)
        store = self._owning_store(entry_id, global_)
        return store.delete(entry_id)

    def list(self, kind: HarnessKind | None = None, *, scope: str = "all") -> list[HarnessEntry]:
        out: list[HarnessEntry] = []
        if scope in ("all", "local"):
            out += self.local.list(kind)
        if scope in ("all", "global"):
            out += self.global_.list(kind)
        return out

    def _split_scope(self, entry_id: str) -> tuple[str, bool]:
        """Accept ids exactly as overview() prints them, e.g. `global:my-note`."""
        prefix, sep, rest = str(entry_id).partition(":")
        if sep and rest and prefix in ("local", "global"):
            return rest, prefix == "global"
        return str(entry_id), False

    def _owning_store(self, entry_id: str, global_: bool) -> HarnessStore:
        if global_:
            return self.global_
        if self.local.get(entry_id) is not None:
            return self.local
        if self.global_.get(entry_id) is not None:
            return self.global_
        return self.local  # if absent, local raises KeyError and lists the known ids

    # ---------- human-readable summary ----------

    def overview(self, *, max_per_kind: int = 20) -> str:
        lines: list[str] = []
        for kind in KINDS:
            entries = [e for e in self.list(kind)]
            lines.append(f"## {kind} ({len(entries)})")
            if not entries:
                lines.append("  (none)")
                continue
            for entry in entries[:max_per_kind]:
                lines.append(f"  [{entry.scope}:{entry.id}] {entry.title}")
            if len(entries) > max_per_kind:
                lines.append(f"  … +{len(entries) - max_per_kind} more")
        return "\n".join(lines)

    def snapshot(self) -> dict[str, Any]:
        return {
            "counts": {kind: len(self.list(kind)) for kind in KINDS},
            "refinements": len(self.local.refinements) + len(self.global_.refinements),
        }

    # ---------- refinement ----------

    def evidence(self, trajectory_path: Path, *, limit: int = 400) -> dict[str, Any]:
        """Gather grounds from the trajectory. The caller does the judging.

        A one-off is not a pattern; only **repeated** signals are candidates. Each
        signal is deliberately tied to the kind of entry it argues for, so the
        answer is not just "here is some data".

        Its blind spot is worth stating, because it cost us one: the most useful
        lesson of the session that produced this function came from a call that
        *succeeded* and returned something stale. Nothing in a trajectory shows
        that. Mechanical signals see repetition, not wrongness.
        """
        records = list(jsonl.read(trajectory_path))[-limit:]

        errors: Counter[str] = Counter()
        commands: Counter[str] = Counter()
        truncated = 0
        for record in records:
            if record.get("event") != "python.exec":
                continue
            if record.get("truncated"):
                truncated += 1
            key = self._code_key(record)
            if record.get("ok", True):
                commands[key] += 1
            else:
                errors[key] += 1

        delegations: Counter[str] = Counter()
        for record in records:
            if record.get("event") == "rlm.turn":
                delegations[str(record.get("name") or "")] += 1

        return {
            "turns": len(records),
            "failed_execs": sum(errors.values()),
            "truncated_outputs": truncated,
            "repeated_errors": [
                {"signature": sig, "count": n, "suggests": "prompt or memory"}
                for sig, n in errors.most_common(10)
                if n > 1
            ],
            "repeated_commands": [
                {"signature": sig, "count": n, "suggests": "skill"}
                for sig, n in commands.most_common(10)
                if n > 1
            ],
            "retasked_subagents": [
                {"name": name, "turns": n, "suggests": "subagent spec"}
                for name, n in delegations.most_common(10)
                if n > 1 and name
            ],
            "existing": self.overview(),
            "past_refinements": self.refinement_history(),
            "how_to_choose": {
                "prompt": "a narrow behavioural policy this project needs",
                "memory": "a durable fact - a port, a path, why a decision was made",
                "skill": "a procedure you keep re-executing, exposed as a Python call",
                "subagent": "context a delegation role always needs",
                "scope": (
                    "local by default; global only for a lesson that will still be "
                    "true in other sessions, or one that names this project explicitly"
                ),
            },
            "note": (
                "Promote only what recurred; each signal above names the kind it "
                "argues for. Prefer the smallest possible change, and read "
                "`past_refinements`: if an earlier one did not deliver its expected "
                "outcome, rolling it back is worth more than adding another. "
                "These signals see repetition, not wrongness - a call that "
                "succeeded and returned something wrong leaves no trace here, so "
                "add what you noticed yourself."
            ),
        }

    @staticmethod
    def _code_key(record: dict) -> str:
        """A stable shape for a cell, so the same procedure counts as the same one."""
        code = str(record.get("code") or "").strip()
        if not code:
            return "(empty cell)"
        for line in code.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line[:120]
        return code.splitlines()[0][:120]

    def refinement_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Past refinements with what they were expected to achieve.

        Nothing here checks an expectation mechanically. Showing it to whoever
        decides the next refinement is how the loop closes without an evaluator:
        a change that plainly did not deliver becomes a rollback candidate rather
        than a permanent one.
        """
        events = self.local.refinements + self.global_.refinements
        recent = sorted(events, key=lambda e: e.created_at)[-limit:]
        return [
            {
                "id": event.id,
                "trigger": event.trigger,
                "changes": event.changes,
                "rationale": event.rationale,
                "expected_outcome": event.expected_outcome,
                "reverted": bool(event.reverted_at),
                "rollback_of": event.rollback_of,
            }
            for event in recent
        ]

    def apply(
        self,
        changes: list[dict[str, Any]],
        *,
        trigger: str,
        evidence: str = "",
        rationale: str = "",
        expected_outcome: str = "",
    ) -> RefinementEvent:
        """Apply a CRUD delta and record it with a `before` snapshot so it reverts.

        If any change fails, everything already applied is rolled back and the
        whole call fails. A half-applied harness is the worst possible outcome.
        """
        if not isinstance(changes, list) or not changes:
            raise ValueError("changes must be a non-empty list")

        before: list[dict[str, Any]] = []
        summary: list[str] = []
        applied: list[tuple[str, HarnessEntry]] = []
        try:
            for change in changes:
                op = change.get("op")
                if op not in VALID_OPS:
                    raise ValueError(f"unknown op {op!r}. one of: {', '.join(VALID_OPS)}")
                if op == "create":
                    entry = self.create(
                        change["kind"],
                        change["title"],
                        change["content"],
                        global_=bool(change.get("global")),
                        path=change.get("path", "general"),
                        source="refine",
                        metadata=change.get("metadata") or {},
                        reference=change.get("reference") or {},
                    )
                    before.append({"op": "create", "id": entry.id, "scope": entry.scope})
                    reason = str(change.get("reason") or "").strip()
                    summary.append(
                        f"create {entry.kind}:{entry.id} — {entry.title}"
                        + (f" ({reason})" if reason else "")
                    )
                    applied.append(("create", entry))
                elif op == "update":
                    current = self.get(change["id"])
                    if current is None:
                        raise KeyError(f"no harness entry {change['id']!r}")
                    before.append({"op": "update", "entry": asdict(current)})
                    fields_ = {k: v for k, v in change.items() if k not in ("op", "id")}
                    entry = self.update(change["id"], **fields_)
                    summary.append(f"update {entry.kind}:{entry.id}")
                    applied.append(("update", entry))
                else:
                    current = self.get(change["id"])
                    if current is None:
                        raise KeyError(f"no harness entry {change['id']!r}")
                    before.append({"op": "delete", "entry": asdict(current)})
                    entry = self.delete(change["id"])
                    summary.append(f"delete {entry.kind}:{entry.id}")
                    applied.append(("delete", entry))
        except Exception:
            self._undo(before)
            raise

        event = RefinementEvent(
            id=f"ref-{uuid.uuid4().hex[:8]}",
            trigger=trigger,
            changes=summary,
            evidence=evidence,
            rationale=rationale,
            expected_outcome=expected_outcome,
            before=before,
        )
        return self.local.record_refinement(event)

    def rollback(self, event_id: str) -> RefinementEvent:
        event = self.local.find_refinement(event_id) or self.global_.find_refinement(event_id)
        if event is None:
            known = [e.id for e in self.local.refinements]
            raise KeyError(f"no refinement {event_id!r}. known: {', '.join(known) or '(none)'}")
        if event.reverted_at:
            raise ValueError(f"refinement {event_id!r} was already rolled back")
        self._undo(event.before)
        from .state import _now

        event.reverted_at = _now()
        event.outcome = "rolled back"
        # Record the reversal as its own event, so history shows that a
        # refinement was tried and withdrawn rather than silently vanishing.
        self.local.record_refinement(
            RefinementEvent(
                id=f"ref-{uuid.uuid4().hex[:8]}",
                trigger="rollback",
                changes=[f"revert {event.id}"],
                rationale=f"the change did not pay off: {event.expected_outcome or event.trigger}",
                rollback_of=event.id,
            )
        )
        self.local.save()
        self.global_.save()
        return event

    def _undo(self, before: list[dict[str, Any]]) -> None:
        """Undo in reverse order, skipping entries that are already gone."""
        for record in reversed(before):
            op = record.get("op")
            try:
                if op == "create":
                    self.delete(f"{record['scope']}:{record['id']}")
                elif op in ("update", "delete"):
                    data = record["entry"]
                    store = self.store(data.get("scope") == "global")
                    store.entries[data["kind"]][data["id"]] = HarnessEntry(**data)
                    store.save()
            except (KeyError, ValueError, TypeError):
                continue


__all__ = ["HarnessEntry", "HarnessKind", "HarnessScope", "HarnessService", "RefinementEvent"]
