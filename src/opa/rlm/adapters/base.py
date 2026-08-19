"""AgentAdapter — 모든 백엔드가 지켜야 하는 계약.

계약이 성립하는 최소 조건은 딱 두 가지다:
  1. 프롬프트 하나로 비대화식 실행이 되고
  2. **세션 id로 재개가 된다** (child의 영속성이 여기서 나온다)

claude / codex 모두 실측으로 만족함을 확인했다 (ARCHITECTURE §5.1).

세션 id의 출처는 백엔드마다 다르다:
  - claude : 우리가 UUID를 발급해서 `--session-id`로 넘긴다
  - codex  : codex가 발급한 걸 첫 턴 출력에서 받아온다
그래서 `preassign_session_id()` 가 None을 돌려줄 수 있고,
`TurnResult.session_id` 로 실제 id가 올라온다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class TurnRequest:
    prompt: str
    cwd: Path
    session_dir: Path
    session_id: str | None = None      # None이면 백엔드가 발급
    resume: bool = False
    model: str | None = None
    system_prompt: str | None = None
    permission_mode: str = "acceptEdits"
    allow_dangerous: bool = False
    timeout: float = 1800.0


@dataclass(frozen=True)
class TurnResult:
    ok: bool
    text: str
    session_id: str | None = None
    tokens: int | None = None
    cost_usd: float | None = None
    raw_path: Path | None = None       # 백엔드 원문 (전체 이벤트 스트림)
    error: str | None = None
    duration_ms: int = 0


class AgentAdapter(Protocol):
    name: str

    def available(self) -> bool:
        """CLI가 PATH에 있고 실행 가능한가."""
        ...

    def preassign_session_id(self) -> str | None:
        """우리가 세션 id를 정할 수 있으면 그걸, 아니면 None."""
        ...

    async def run(self, request: TurnRequest) -> TurnResult:
        """한 턴 실행. `resume=True`면 기존 컨텍스트를 이어받는다."""
        ...
