"""Harness 상태 스토어.

원본 `_ref/prime-agent/prime-agent-runtime/src/rlm/harness.py`의 파일 스키마와
호환되게 유지한다 (원본 세션 이식 + 원본 문서 재사용):

    {"schema": 1,
     "entries": {"prompt": {id: {...}}, "memory": {...}, "skill": {...},
                 "subagent": {...}},
     "refinements": [{id, trigger, changes, evidence, outcome, created_at, ...}]}

원본과의 차이 하나: RefinementEvent에 `before` 스냅샷을 더 넣는다.
원본은 변경 내역을 문자열 리스트로만 남겨서 **정확한 rollback이 불가능**하다.
추가 필드라 원본이 읽어도 무시할 뿐이므로 양방향 호환은 유지된다.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

HarnessKind = Literal["prompt", "memory", "skill", "subagent"]
HarnessScope = Literal["local", "global"]

KINDS: tuple[HarnessKind, ...] = ("prompt", "memory", "skill", "subagent")
SCHEMA_VERSION = 1
STATE_FILE_NAME = "harness_state.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def slug(raw: str, fallback: str = "entry") -> str:
    """Make a stable id from a title.

    Keeps Unicode word characters. Stripping non-ASCII would collapse every
    Korean/Japanese/Chinese title onto the same fallback id, so ids would
    collide and mean nothing.
    """
    normalized = re.sub(r"[^\w]+", "-", raw.strip().lower(), flags=re.UNICODE).strip("-_")
    return (normalized or fallback)[:60]


@dataclass
class HarnessEntry:
    """A reusable prompt, memory, skill, or subagent record."""

    id: str
    kind: HarnessKind
    title: str
    content: str
    path: str = "general"
    scope: HarnessScope = "local"
    reference: dict[str, Any] = field(default_factory=dict)
    arguments: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "agent"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    version: int = 1


@dataclass
class RefinementEvent:
    """한 번의 harness 개선 기록. `before` 가 있어야 정확한 rollback이 된다."""

    id: str
    trigger: str
    changes: list[str]
    evidence: str = ""
    outcome: str = ""
    created_at: str = field(default_factory=_now)
    before: list[dict[str, Any]] = field(default_factory=list)
    reverted_at: str | None = None


_ENTRY_FIELDS = {f.name for f in fields(HarnessEntry)}
_EVENT_FIELDS = {f.name for f in fields(RefinementEvent)}


class HarnessStore:
    """스코프 하나 = 파일 하나."""

    def __init__(self, file_path: Path, scope: HarnessScope = "local") -> None:
        self.file_path = Path(file_path)
        self.scope: HarnessScope = scope
        self.entries: dict[HarnessKind, dict[str, HarnessEntry]] = {k: {} for k in KINDS}
        self.refinements: list[RefinementEvent] = []
        self.load()

    # ---------- 영속 ----------

    def load(self) -> HarnessStore:
        self.entries = {k: {} for k in KINDS}
        self.refinements = []
        if not self.file_path.exists():
            return self
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # 깨진 상태 파일이 커널을 죽이거나 개선을 막으면 안 된다.
            # 빈 것으로 취급하고 다음 save()에서 깨끗이 다시 쓴다.
            return self
        if not isinstance(data, dict):
            return self

        raw_entries = data.get("entries")
        if isinstance(raw_entries, dict):
            for kind in KINDS:
                for entry_id, raw in (raw_entries.get(kind) or {}).items():
                    entry = self._coerce_entry(entry_id, kind, raw)
                    if entry is not None:
                        self.entries[kind][entry.id] = entry

        for raw in data.get("refinements") or []:
            if isinstance(raw, dict) and isinstance(raw.get("id"), str):
                payload = {k: v for k, v in raw.items() if k in _EVENT_FIELDS}
                payload.setdefault("trigger", "")
                payload.setdefault("changes", [])
                try:
                    self.refinements.append(RefinementEvent(**payload))
                except TypeError:
                    continue
        return self

    def _coerce_entry(self, entry_id: Any, kind: HarnessKind, raw: Any) -> HarnessEntry | None:
        if not isinstance(raw, dict):
            return None
        data = {k: v for k, v in raw.items() if k in _ENTRY_FIELDS}
        data["id"] = str(entry_id)
        data["kind"] = kind
        if not isinstance(data.get("title"), str) or not isinstance(data.get("content"), str):
            return None
        if not isinstance(data.get("path"), str):
            data["path"] = "general"
        if data.get("scope") not in ("local", "global"):
            data["scope"] = self.scope
        if not isinstance(data.get("source"), str):
            data["source"] = "agent"
        for key in ("reference", "arguments", "metadata"):
            if not isinstance(data.get(key), dict):
                data[key] = {}
        try:
            data["version"] = int(data.get("version", 1))
        except (TypeError, ValueError):
            data["version"] = 1
        try:
            return HarnessEntry(**data)
        except TypeError:
            return None

    def save(self) -> HarnessStore:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema": SCHEMA_VERSION,
            "entries": {
                kind: {eid: asdict(e) for eid, e in records.items()}
                for kind, records in self.entries.items()
            },
            "refinements": [asdict(e) for e in self.refinements],
        }
        # 원자적 교체. 쓰다 죽어도 반쪽짜리 상태 파일이 남지 않는다.
        tmp = self.file_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.file_path)
        return self

    # ---------- CRUD ----------

    def create(self, kind: HarnessKind, title: str, content: str, **kw) -> HarnessEntry:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}. one of: {', '.join(KINDS)}")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a non-empty string")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content must be a non-empty string")
        entry_id = kw.pop("id", None) or self._unique_id(kind, title)
        entry = HarnessEntry(
            id=entry_id, kind=kind, title=title.strip(), content=content, scope=self.scope, **kw
        )
        self.entries[kind][entry.id] = entry
        self.save()
        return entry

    def _unique_id(self, kind: HarnessKind, title: str) -> str:
        base = slug(title)
        if base not in self.entries[kind]:
            return base
        return f"{base}-{uuid.uuid4().hex[:4]}"

    def get(self, entry_id: str) -> HarnessEntry | None:
        for kind in KINDS:
            if entry_id in self.entries[kind]:
                return self.entries[kind][entry_id]
        return None

    def update(self, entry_id: str, **changes) -> HarnessEntry:
        entry = self.get(entry_id)
        if entry is None:
            raise KeyError(f"no harness entry {entry_id!r}. {self._known()}")
        for key, value in changes.items():
            if key in ("id", "kind"):
                raise ValueError(f"{key} cannot be changed")
            if key not in _ENTRY_FIELDS:
                raise ValueError(f"unknown field {key!r}")
            setattr(entry, key, value)
        entry.updated_at = _now()
        entry.version += 1
        self.save()
        return entry

    def delete(self, entry_id: str) -> HarnessEntry:
        entry = self.get(entry_id)
        if entry is None:
            raise KeyError(f"no harness entry {entry_id!r}. {self._known()}")
        del self.entries[entry.kind][entry.id]
        self.save()
        return entry

    def list(self, kind: HarnessKind | None = None) -> list[HarnessEntry]:
        kinds = (kind,) if kind else KINDS
        out: list[HarnessEntry] = []
        for k in kinds:
            out.extend(self.entries[k].values())
        return sorted(out, key=lambda e: (e.kind, e.created_at))

    def _known(self) -> str:
        ids = [e.id for e in self.list()]
        return f"known ids: {', '.join(ids) if ids else '(none)'}"

    # ---------- refinement ----------

    def record_refinement(self, event: RefinementEvent) -> RefinementEvent:
        self.refinements.append(event)
        self.save()
        return event

    def find_refinement(self, event_id: str) -> RefinementEvent | None:
        return next((e for e in self.refinements if e.id == event_id), None)
