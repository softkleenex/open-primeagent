"""Phase 2 Exit criteria — 진짜 child 에이전트를 띄운다.

`child` 마커가 붙어 있고 기본 실행에서 **제외**된다:
실제 CLI 인증과 토큰 쿼터가 필요하기 때문이다. 돌리려면:

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

    # ① rlm() 은 결과를 기다리지 않고 핸들만 돌려준다
    out = await py(server, f"await rlm('Reply with exactly: {TOKEN}', name='probe', model='sonnet')")
    assert "probe" in out and "running" in out

    # ② 결과는 부모 메일박스로 온다
    inbox = await wait_for_inbox(runtime, 1)
    assert TOKEN in inbox[0]["message"]
    assert inbox[0]["sender"] == "probe"

    # ③ 커널을 재시작해도 child는 registry에 남아있다
    await server.call_tool("opa_kernel", {"action": "restart"})
    assert "probe" in await py(server, "[s.name for s in await rlm.list_subagents()]")

    # ④ 이전 컨텍스트를 유지한 채 이어서 일한다 — 이 프로젝트가 동작한다는 유일한 증거
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
