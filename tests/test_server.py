"""The MCP surface - the tool ceiling is a premise of this project."""

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
    """More tools would contradict "give it Python". Nail the ceiling down in a test."""
    tools = await server.list_tools()
    assert len(tools) <= MAX_TOOLS
    assert {t.name for t in tools} <= {"opa_python", "opa_status", "opa_kernel", "opa_bootstrap"}


async def test_every_tool_is_described(server):
    for tool in await server.list_tools():
        assert tool.description and len(tool.description) > 40


async def test_status_before_kernel_boots(server):
    """The kernel boots lazily; asking for status must not start one."""
    result = await server.call_tool("opa_status", {})
    state = json.loads(result.content[0].text)
    assert state["kernel"]["alive"] is False
    assert server._opa_runtime.kernel_if_started is None
