"""HostBridge — 커널/스킬/child 가 호스트(이 MCP 서버)를 호출하는 통로.

원본은 Jupyter comm(`host.request`)을 쓰지만 우리는 Unix domain socket을 쓴다.
이유는 ARCHITECTURE §2 참조: 커널 재시작과 독립적이고, 커널이 아닌 프로세스
(스킬 서브프로세스, child 에이전트)도 같은 통로를 쓸 수 있다.

프로토콜: 한 줄 = JSON 하나.
    →  {"id": "1", "type": "rlm.run", "payload": {...}}
    ←  {"id": "1", "status": "ok",    ...}
    ←  {"id": "1", "status": "error", "error": "..."}

타입 이름은 원본과 동일하게 유지한다 (rlm.run / rlm.list_subagents /
rlm.delete_subagent / rlm.find_models). 원본 문서와 스킬을 그대로 참조하기 위해서.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class HostBridge:
    """소켓을 listen 하고 request type 별 핸들러로 디스패치한다."""

    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path
        self._handlers: dict[str, Handler] = {}

    def register(self, request_type: str, handler: Handler) -> None:
        """`rlm.run` 같은 타입에 핸들러를 건다."""
        raise NotImplementedError

    async def serve(self) -> None:
        """소켓 수락 루프. 커널보다 먼저 떠 있어야 한다."""
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError
