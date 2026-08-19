"""ChildRegistry — child가 일회용이 아니게 만드는 것.

커널 재시작, 컨텍스트 compaction, 호스트 재시작 이후에도
`await rlm.list_subagents()` 가 같은 child를 돌려줘야 한다.
그래서 registry는 커널 메모리가 아니라 디스크에 산다.

레이아웃:
    children/
      index.json                 name -> rlm_child_id
      <rlm_child_id>/child.json  ChildRecord
      <rlm_child_id>/turns.jsonl 턴 기록
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

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

    # ---------- 영속 ----------

    def child_dir(self, rlm_child_id: str) -> Path:
        return self.dir / rlm_child_id

    def load(self) -> ChildRegistry:
        """디스크에서 복구. 서버 부팅 시 반드시 먼저 호출."""
        self._records.clear()
        if not self.dir.exists():
            return self
        for record_file in sorted(self.dir.glob("*/child.json")):
            try:
                data = json.loads(record_file.read_text(encoding="utf-8"))
                record = ChildRecord(**data)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue  # 깨진 항목 하나가 나머지 child를 막으면 안 된다
            self._records[record.rlm_child_id] = record
        return self

    def _persist(self, record: ChildRecord) -> None:
        directory = self.child_dir(record.rlm_child_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "child.json").write_text(
            json.dumps(asdict(record), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ---------- CRUD ----------

    def add(self, record: ChildRecord) -> ChildRecord:
        if self.get(record.name) is not None:
            raise ValueError(
                f"a sub-agent named {record.name!r} already exists. "
                f"Send it a message instead of creating a duplicate."
            )
        self._records[record.rlm_child_id] = record
        self._persist(record)
        return record

    def update(self, rlm_child_id: str, **changes) -> ChildRecord:
        record = self._records[rlm_child_id]
        for key, value in changes.items():
            setattr(record, key, value)
        record.updated_at = _now()
        self._persist(record)
        return record

    def get(self, selector: str) -> ChildRecord | None:
        """rlm_child_id 또는 name으로 찾는다."""
        if selector in self._records:
            return self._records[selector]
        for record in self._records.values():
            if record.name == selector:
                return record
        return None

    def list(self) -> list[ChildRecord]:
        return sorted(self._records.values(), key=lambda r: r.created_at)

    def delete(self, selector: str) -> ChildRecord:
        """명시적 호출로만 지운다. 자동 정리는 하지 않는다 — 상주가 기본값이다."""
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

    # ---------- 턴 기록 ----------

    def record_turn(self, rlm_child_id: str, entry: dict) -> None:
        jsonl.append(self.child_dir(rlm_child_id) / "turns.jsonl", {"at": _now(), **entry})

    def turns(self, rlm_child_id: str, *, limit: int | None = None) -> list[dict]:
        path = self.child_dir(rlm_child_id) / "turns.jsonl"
        records = list(jsonl.read(path))
        return records[-limit:] if limit else records
