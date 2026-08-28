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


async def test_a_child_can_report_before_it_finishes(config):
    """The push channel, against a real child agent.

    Also checks that scoping --allowedTools to the push tool does not take the
    child's other tools away: it has to read a file *and* notify.
    """
    if shutil.which("claude") is None:
        pytest.skip("claude CLI is not installed")

    (config.workspace / "secret.py").write_text(
        "API_KEY = 'sk-live-abc123'\n", encoding="utf-8"
    )
    pushy = config.__class__(**{**config.__dict__, "child_can_message_parent": True})
    server = build_server(pushy)
    runtime = server._opa_runtime
    await runtime.start_bridge()
    try:
        prompt = (
            "First read secret.py in this directory. Then call opa_notify_parent "
            "with a one-line note about what you found. Then reply with only DONE."
        )
        await py(
            server,
            f"await rlm({prompt!r}, name='probe', model='sonnet', can_message_parent=True)",
        )
        for _ in range(180):
            if any(m.get("mid_run") for m in runtime.rlm.mailbox.read()):
                break
            await asyncio.sleep(1)

        inbox = runtime.rlm.mailbox.read()
        pushes = [m for m in inbox if m.get("mid_run")]
        assert pushes, "the child never pushed a mid-run note"
        assert pushes[0]["sender"] == "probe"
        # the child still had its ordinary tools
        assert any("API_KEY" in m["message"] or "sk-live" in m["message"] for m in inbox)
    finally:
        await runtime.shutdown()
