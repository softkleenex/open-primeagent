"""Phase 2 exit criteria - spawns a real child agent.

Marked `child` and **excluded** from the default run, because it needs real CLI
auth and token quota. To run it:

    uv run pytest -m child -s
"""

from __future__ import annotations

import asyncio
import shutil

import pytest

from opa.server import build_server

pytestmark = [pytest.mark.slow, pytest.mark.child]

TOKEN = "ALPHA-7"


@pytest.fixture
async def server(config):
    if shutil.which("claude") is None:
        pytest.skip("claude CLI is not installed")
    srv = build_server(config)
    yield srv
    await srv._opa_runtime.shutdown()


async def py(server, code):
    return (await server.call_tool("opa_python", {"code": code})).content[0].text


async def wait_for_inbox(runtime, count, timeout=180):
    for _ in range(timeout):
        if runtime.rlm.mailbox.count() >= count:
            return runtime.rlm.mailbox.read()
        await asyncio.sleep(1)
    raise AssertionError(f"parent mailbox never reached {count} messages")


async def test_rlm_is_non_blocking_and_child_survives_a_kernel_restart(server):
    runtime = server._opa_runtime

    # 1. rlm() returns a handle without waiting for the result
    out = await py(server, f"await rlm('Reply with exactly: {TOKEN}', name='probe', model='sonnet')")
    assert "probe" in out and "running" in out

    # 2. the result arrives in the parent mailbox
    inbox = await wait_for_inbox(runtime, 1)
    assert TOKEN in inbox[0]["message"]
    assert inbox[0]["sender"] == "probe"

    # 3. the child stays in the registry across a kernel restart
    await server.call_tool("opa_kernel", {"action": "restart"})
    assert "probe" in await py(server, "[s.name for s in await rlm.list_subagents()]")

    # 4. it continues with its earlier context - the only proof this project works
    await py(
        server,
        "await agent_message.send('What token did you just say? "
        "Reply with only the token.', receiver_name='probe')",
    )
    inbox = await wait_for_inbox(runtime, 2)
    assert TOKEN in inbox[-1]["message"], "child forgot its earlier turn — resume is broken"

    record = runtime.rlm.registry.get("probe")
    assert record.turns == 2
    assert record.tokens > 0
