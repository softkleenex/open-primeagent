"""Harness 상태 스토어.

원본 `_ref/prime-agent/prime-agent-runtime/src/rlm/harness.py`의 스키마와
호환되게 유지한다 (원본 세션 이식 가능성 + 원본 문서 재사용).

  kind  : prompt | subagent | skill | memory
  scope : local (세션) | global (~/.opa)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

HarnessKind = Literal["prompt", "subagent", "skill", "memory"]
HarnessScope = Literal["local", "global"]


@dataclass
class HarnessEntry:
    id: str
    kind: HarnessKind
    title: str
    content: str
    path: str = "general"
    scope: HarnessScope = "local"
    reference: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "agent"       # "agent" | "user" | "refine"
    created_at: str = ""
    updated_at: str = ""
    version: int = 1


@dataclass
class RefinementEvent:
    """rollback을 위해 delta를 통째로 남긴다. base system prompt는 절대 건드리지 않는다."""

    id: str
    at: str
    summary: str
    before: list[HarnessEntry]
    after: list[HarnessEntry]


class HarnessState:
    def __init__(self, local_path: Path, global_path: Path) -> None:
        self.local_path = local_path
        self.global_path = global_path

    def create(self, kind: HarnessKind, title: str, content: str, **kw) -> HarnessEntry: ...
    def read(self, id: str) -> HarnessEntry | None: ...
    def update(self, id: str, **kw) -> HarnessEntry: ...
    def delete(self, id: str) -> HarnessEntry: ...
    def overview(self) -> str:
        """`[local:id] title` 형태의 사람이 읽는 요약."""
    def rollback(self, event_id: str) -> None: ...
