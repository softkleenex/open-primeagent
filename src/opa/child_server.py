"""`opa-child` - the one-tool MCP server attached to a child agent.

A child that can only speak when it finishes has to go dark for the whole run.
This lets it report mid-run instead.

It is deliberately **not** the full opa server: one tool, no `rlm`, so the model
is never offered a way to spawn grandchildren.

That is a nudge, not a boundary, and this file used to claim otherwise. A child
process holds `$OPA_HOST_SOCKET` and, with a shell, can speak the bridge
protocol directly no matter what its tool list says. The boundary lives in the
bridge: each caller has a token, and a child's token authorises exactly one
request type. `0600` on the socket only keeps out other *users*; our own
children share our uid.
"""

from __future__ import annotations

import asyncio

from mcp.server.mcpserver import MCPServer

from . import __version__

ENV_CHILD_NAME = "OPA_CHILD_NAME"
SERVER_NAME = "opa_child"

DESCRIPTION = """\
Send a progress note to the agent that spawned you, without waiting until you
finish. Use it when you have found something the parent should act on now, or
when a long task has reached a milestone worth reporting.

Keep it short: a finding, a milestone, or a blocker. Your final answer is
delivered automatically when you are done, so do not duplicate it here.
"""

INSTRUCTIONS = """\
You were started as a sub-agent by open-primeagent. You can report progress to
your parent mid-run with opa_notify_parent; your final answer is delivered
automatically when you finish.
"""


def build_server() -> MCPServer:
    server = MCPServer(name=SERVER_NAME, version=__version__, instructions=INSTRUCTIONS)

    @server.tool(name="opa_notify_parent", description=DESCRIPTION)
    async def opa_notify_parent(message: str) -> str:
        from opa_runtime.client import host_request

        if not isinstance(message, str) or not message.strip():
            return "nothing sent: message was empty"
        try:
            # No sender field: the bridge takes our identity from the token in
            # our environment, which we cannot choose.
            await host_request(
                "agent_message.send",
                {"message": message.strip(), "receiver_role": "parent"},
            )
        except RuntimeError as exc:
            # The parent may have shut down. Say so rather than failing the child.
            return f"could not reach the parent: {exc}"
        return "delivered to the parent"

    return server


def main() -> None:
    asyncio.run(build_server().run_stdio_async())


if __name__ == "__main__":
    main()
