"""agent-to-agent messaging.

메일박스는 `<session>/mailbox/<name>.jsonl`.

  parent → child : 어댑터 `resume`으로 새 턴을 연다.
                   child는 **이전 컨텍스트를 유지한 채** 이어서 일한다.
                   이것이 "child가 일회용이 아니다"의 실제 구현이다.

  child → parent : Phase 2 — 어댑터가 child 최종 출력을 캡처해 parent 메일박스에 적재
                   Phase 3 — child에 opa MCP를 붙이고 OPA_ROLE=child를 주면
                             작업 도중에도 push 가능 (socket 브릿지를 택한 이유)
"""

from __future__ import annotations

from typing import Literal

Role = Literal["parent", "child"]


class Mailbox:
    async def send(
        self,
        message: str,
        *,
        receiver_role: Role,
        receiver_name: str | None = None,
    ) -> dict:
        raise NotImplementedError

    async def poll(self, *, since: int = 0) -> list[dict]:
        """호스트 턴 루프를 소유하지 않으므로 수신은 push가 아니라 pull이다.
        (ARCHITECTURE §7의 한계)"""
        raise NotImplementedError
