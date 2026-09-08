"""`agent_message` - hand follow-up work to a child that already did some.

    await agent_message.send(
        "re-check it now that I have fixed the code",
        receiver_role="child", receiver_name="api-reviewer",
    )

The child continues **with its earlier context intact**, which always beats
creating a new one. Collection is a pull, because we do not own the host's turn
loop:

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

    async def list_agents(self) -> dict[str, Any]:
        """Who you can address from here.

        Returns `current` (name, id, depth) and `entries`, each carrying a
        `relationship` of "parent" or "child".

        Upstream also lists siblings. We do not: a child that could address a
        sibling could re-task work it does not own, so a child sees only the
        parent here. The list reflects the authority the bridge will actually
        grant, rather than a family tree it would then refuse to act on.
        """
        return await host_request("agent_message.list_agents")

    async def inbox(self, *, since: int = 0) -> list[dict[str, Any]]:
        """Read the parent mailbox, where child results arrive.

        Records with `mid_run: true` are progress notes a child pushed while it
        was still working, rather than its final answer.
        """
        payload = await host_request("agent_message.inbox", {"since": since})
        return payload["messages"]


agent_message = _AgentMessage()
