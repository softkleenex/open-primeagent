"""L1 — 진짜 커널을 띄운다. ROADMAP Phase 1 Exit criteria 그 자체.

느리므로 `-m "not slow"` 로 뺄 수 있게 표시한다.
"""

from __future__ import annotations

import json

import pytest

from opa.server import build_server

pytestmark = pytest.mark.slow


@pytest.fixture
async def server(config):
    srv = build_server(config)
    yield srv
    await srv._opa_runtime.shutdown()


async def call(server, name, args):
    return (await server.call_tool(name, args)).content[0].text


async def test_exit1_state_persists_across_calls(server):
    await call(server, "opa_python", {"code": "files = [f'f{i}.py' for i in range(500)]"})
    assert "500" in await call(server, "opa_python", {"code": "len(files)"})


async def test_functions_and_imports_persist(server):
    await call(server, "opa_python", {"code": "import math\ndef area(r): return math.pi * r * r"})
    assert "12.57" in await call(server, "opa_python", {"code": "round(area(2), 2)"})


async def test_top_level_await_works(server):
    """IPython autoawait 가 처리한다 — nest_asyncio 불필요."""
    out = await call(server, "opa_python", {"code": "import asyncio\nawait asyncio.sleep(0.01)\n'ok'"})
    assert "'ok'" in out


async def test_exit2_large_output_is_truncated_and_stored(server, config):
    out = await call(server, "opa_python", {"code": "print('x' * 30000)"})
    assert len(out) < 30000
    saved = list(config.root.rglob("outputs/*.txt"))
    assert saved and len(saved[0].read_text()) > 29000


async def test_error_is_captured_without_ansi(server):
    out = await call(server, "opa_python", {"code": "1/0"})
    assert "ZeroDivisionError" in out
    assert "\x1b[" not in out


async def test_rlm_symbol_is_preloaded(server):
    """rlm 은 MCP 도구가 아니라 커널 안 심볼이다."""
    assert "_RLM" in await call(server, "opa_python", {"code": "type(rlm).__name__"})


async def test_exit3_restart_clears_vars_but_keeps_session(server, config):
    await call(server, "opa_python", {"code": "files = [1, 2, 3]"})
    await call(server, "opa_kernel", {"action": "restart"})
    assert "False" in await call(server, "opa_python", {"code": "'files' in dir()"})
    assert "_RLM" in await call(server, "opa_python", {"code": "type(rlm).__name__"})
    trajectory = next(config.root.rglob("trajectory.jsonl"))
    events = [json.loads(line)["event"] for line in trajectory.read_text().splitlines()]
    assert "kernel.restart" in events


async def test_timeout_interrupts_instead_of_hanging(server):
    out = await call(server, "opa_python", {"code": "import time; time.sleep(30)", "timeout": 2})
    assert "Timeout" in out
