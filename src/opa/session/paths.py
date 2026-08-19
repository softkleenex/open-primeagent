"""세션 디렉터리 레이아웃.

    .opa/
    └── sessions/<session_id>/
        ├── session.json          세션 메타
        ├── trajectory.jsonl      호스트↔opa 전 이벤트 (refine의 입력)
        ├── outputs/<n>.txt       잘라내기 전 전문 출력
        ├── harness/harness_state.json
        ├── goal.json
        ├── mailbox/<name>.jsonl
        └── children/
            ├── index.json        ChildRegistry
            └── <rlm_child_id>/
                ├── child.json
                └── turns.jsonl

커널 재시작·컨텍스트 compaction·호스트 재시작 후에도 복구되어야 하는 것은
전부 이 아래에 있다. 커널 메모리에만 있는 것은 사용자 변수뿐이다.
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
    def harness_state(self) -> Path:
        return self.dir / "harness" / "harness_state.json"

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
        """필요한 디렉터리를 만든다."""
        for directory in (self.dir, self.outputs, self.mailbox, self.children,
                          self.harness_state.parent):
            directory.mkdir(parents=True, exist_ok=True)
        return self
