"""`agent_message` — 이전에 일했던 child에게 후속 작업을 준다.

    await agent_message.send(
        "방금 수정한 코드까지 다시 검사해",
        receiver_role="child", receiver_name="api-reviewer",
    )

child는 **이전 컨텍스트를 유지한 채** 이어서 일한다. 새로 만드는 것보다 항상 낫다.
결과 수거는 pull이다 (호스트의 턴 루프를 우리가 소유하지 않기 때문):

    for m in await agent_message.inbox():
        print(m["sender"], m["message"][:200])
"""

from __future__ import annotations

from typing import Any

from .client import host_request


class _AgentMessage:
    async def send(
        self,
        message: str,
        *,
        receiver_name: str,
        receiver_role: str = "child",
    ) -> dict[str, Any]:
        if receiver_role != "child":
            raise NotImplementedError(
                "only receiver_role='child' is supported from the parent kernel"
            )
        return await host_request(
            "agent_message.send", {"message": message, "receiver_name": receiver_name}
        )

    async def inbox(self, *, since: int = 0) -> list[dict[str, Any]]:
        """부모 메일박스를 읽는다. child의 결과가 여기로 온다."""
        payload = await host_request("agent_message.inbox", {"since": since})
        return payload["messages"]


agent_message = _AgentMessage()
