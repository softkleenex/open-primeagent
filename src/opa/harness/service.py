"""HarnessService — local/global 두 스코프를 묶고, 개선(refinement)을 적용한다.

`H = (ρ prompts, G subagents, K skills, M memory)` 의 CRUD가 여기 다 있다.

**중요**: 무엇을 바꿀지 *판단*하는 것은 여기가 아니다.
호스트는 우리에게 모델을 빌려주지 않는다 (Claude Code는 MCP `sampling` 미지원 —
docs/evolution.md §1.1 실측). 그래서 판단은 호출자(호스트 에이전트 또는 refiner
child)가 하고, 우리는 **근거를 모아주고(evidence) 적용·기록·되돌리기**를 한다.
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

    # ---------- CRUD (스코프 라우팅) ----------

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
        """`global:my-note` 처럼 overview()가 보여준 id를 그대로 받는다."""
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
        return self.local  # 없으면 local이 KeyError를 내며 known ids를 알려준다

    # ---------- 사람이 읽는 요약 ----------

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
        """trajectory에서 '무엇을 바꿀지' 판단할 근거를 모은다. 판단은 호출자가 한다.

        한 번 겪은 일은 승격하지 않는다 — **반복된 것**만 올린다. 그래서
        반복 신호(같은 에러, 같은 코드 패턴)를 세어서 돌려준다.
        """
        records = list(jsonl.read(trajectory_path))[-limit:]
        errors: Counter[str] = Counter()
        for record in records:
            if record.get("event") == "python.exec" and not record.get("ok", True):
                errors[self._error_key(record)] += 1
        return {
            "turns": len(records),
            "failed_execs": sum(errors.values()),
            "repeated_errors": [
                {"signature": sig, "count": n} for sig, n in errors.most_common(10) if n > 1
            ],
            "existing": self.overview(),
            "note": (
                "Promote only patterns you saw more than once. "
                "Prefer the smallest possible change."
            ),
        }

    @staticmethod
    def _error_key(record: dict) -> str:
        code = str(record.get("code") or "")
        return code.strip().splitlines()[0][:120] if code.strip() else "(empty cell)"

    def apply(
        self,
        changes: list[dict[str, Any]],
        *,
        trigger: str,
        evidence: str = "",
    ) -> RefinementEvent:
        """CRUD delta를 적용하고, **되돌릴 수 있게** before 스냅샷과 함께 기록한다.

        하나라도 실패하면 앞서 적용한 것들을 되돌리고 통째로 실패시킨다.
        반쪽만 적용된 harness가 남는 게 제일 나쁘다.
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
                    summary.append(f"create {entry.kind}:{entry.id} — {entry.title}")
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
        self.local.save()
        self.global_.save()
        return event

    def _undo(self, before: list[dict[str, Any]]) -> None:
        """역순으로 되돌린다. 이미 사라진 항목은 조용히 넘긴다."""
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
