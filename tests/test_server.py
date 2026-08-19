"""MCP 표면 — 도구 개수 상한이 이 프로젝트의 전제다."""

from __future__ import annotations

import json

import pytest

from opa.server import MAX_TOOLS, build_server


@pytest.fixture
async def server(config):
    srv = build_server(config)
    yield srv
    await srv._opa_runtime.shutdown()


async def test_tool_surface_stays_small(server):
    """도구를 늘리면 "Python을 줘라"는 철학과 정반대가 된다. 상한을 테스트로 못박는다."""
    tools = await server.list_tools()
    assert len(tools) <= MAX_TOOLS
    assert {t.name for t in tools} <= {"opa_python", "opa_status", "opa_kernel", "opa_bootstrap"}


async def test_every_tool_is_described(server):
    for tool in await server.list_tools():
        assert tool.description and len(tool.description) > 40


async def test_status_before_kernel_boots(server):
    """커널은 지연 부팅한다 — status 조회만으로 커널이 뜨면 안 된다."""
    result = await server.call_tool("opa_status", {})
    state = json.loads(result.content[0].text)
    assert state["kernel"]["alive"] is False
    assert server._opa_runtime.kernel_if_started is None
