"""AgentAdapter — 모든 백엔드가 지켜야 하는 계약.

계약이 성립하는 최소 조건은 딱 두 가지다:
  1. 프롬프트 하나로 비대화식 실행이 되고
  2. **세션 id로 재개가 된다** (child의 영속성이 여기서 나온다)

claude / codex 모두 실측으로 만족함을 확인했다 (ARCHITECTURE §5.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class NativeSession:
    session_id: str
    adapter: str


@dataclass(frozen=True)
class TurnResult:
    ok: bool
    text: str
    tokens: int | None
    raw_path: Path | None   # 전체 스트림 원문


class AgentAdapter(Protocol):
    name: str

    def available(self) -> bool:
        """CLI가 PATH에 있고 실행 가능한가."""
        ...

    async def spawn(self, spec: Any, session_dir: Path) -> tuple[NativeSession, TurnResult]:
        ...

    async def resume(self, sess: NativeSession, prompt: str, session_dir: Path) -> TurnResult:
        ...

    def parse_event(self, line: str) -> dict | None:
        """스트림 한 줄 → 정규화된 이벤트. 포맷 차이를 여기서 흡수한다."""
        ...
