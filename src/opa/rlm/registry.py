"""ChildRegistry — child가 일회용이 아니게 만드는 것.

커널 재시작, 컨텍스트 compaction, 호스트 재시작 이후에도
`await rlm.list_subagents()` 가 같은 child를 돌려줘야 한다.
그래서 registry는 커널 메모리가 아니라 디스크에 산다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ChildStatus = Literal["running", "completed", "error"]


@dataclass
class TurnRef:
    index: int
    prompt_preview: str
    started_at: str
    ended_at: str | None
    status: ChildStatus
    tokens: int | None = None


@dataclass
class ChildRecord:
    rlm_child_id: str          # opa-<8hex>
    name: str                  # "api-reviewer" — 재호출 시의 주소
    adapter: str               # "claude-code" | "codex"
    native_session_id: str     # 호스트 CLI가 아는 세션 id
    session_dir: Path
    cwd: Path
    status: ChildStatus
    model: str | None = None
    spec: str | None = None    # harness의 subagent 스펙 (append-system-prompt로 주입)
    created_at: str = ""
    turns: list[TurnRef] = field(default_factory=list)


class ChildRegistry:
    def __init__(self, children_dir: Path) -> None:
        self.dir = children_dir

    def load(self) -> None:
        """디스크에서 복구. 서버 부팅 시 반드시 먼저 호출."""
        raise NotImplementedError

    def add(self, record: ChildRecord) -> None:
        raise NotImplementedError

    def get(self, selector: str) -> ChildRecord | None:
        """rlm_child_id 또는 name으로 찾는다."""
        raise NotImplementedError

    def list(self) -> list[ChildRecord]:
        raise NotImplementedError

    def delete(self, selector: str) -> ChildRecord:
        """명시적 호출로만 지운다. 자동 정리는 하지 않는다 — 상주가 기본값이다."""
        raise NotImplementedError
