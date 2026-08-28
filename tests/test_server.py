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


async def test_bootstrap_reports_what_it_touched(server, config):
    """The fourth tool, end to end through the MCP surface."""
    target = config.workspace / "CLAUDE.md"
    original = "# mine\n\n- a rule I wrote\n"
    target.write_text(original, encoding="utf-8")
    runtime = server._opa_runtime
    runtime.harness.create("prompt", "run generate", "after migrations")

    first = (await server.call_tool("opa_bootstrap", {})).content[0].text
    assert "projected harness for: claude-code" in first
    assert "updated:" in first
    assert original.rstrip("\n") in target.read_text(encoding="utf-8")

    second = (await server.call_tool("opa_bootstrap", {})).content[0].text
    assert "already current" in second

    removed = (await server.call_tool("opa_bootstrap", {"remove": True})).content[0].text
    assert "removed the open-primeagent block" in removed
    assert target.read_text(encoding="utf-8") == original


async def test_bootstrap_on_a_clean_tree_says_nothing_to_remove(server):
    out = (await server.call_tool("opa_bootstrap", {"remove": True})).content[0].text
    assert "nothing to remove" in out


async def test_status_reports_harness_counts(server):
    runtime = server._opa_runtime
    runtime.harness.create("memory", "ports", "api=8080")
    state = json.loads((await server.call_tool("opa_status", {})).content[0].text)
    assert state["harness"]["counts"]["memory"] == 1
    assert state["subagents"] == []
    assert state["mailbox_unread"] == 0


async def test_status_surfaces_the_long_run_layer(server):
    """After a compaction this one call has to say what was being pursued."""
    runtime = server._opa_runtime
    runtime.goals.create("keep the suite green", token_budget=1000)
    runtime.schedule.create("check the deploy", in_seconds=0)

    state = json.loads((await server.call_tool("opa_status", {})).content[0].text)
    assert state["goal"]["goal"]["objective"] == "keep the suite green"
    assert state["schedule"] == {"entries": 1, "due_now": 1}
    assert state["autonomous"]["running"] is False

    # looking at status must not consume what is due
    assert len(runtime.schedule.due(collect=False)) == 1


def test_the_kernel_stack_is_not_imported_until_a_kernel_is_needed():
    """The kernel boots lazily, so the import graph should be lazy too.

    jupyter_client pulls in zmq and jupyter_core. A host that registers the
    server but never runs Python should not pay for that at startup.
    """
    import subprocess
    import sys

    probe = (
        "import sys; import opa.server; "
        "loaded = [m for m in sys.modules if m.startswith(('jupyter_client', 'zmq'))]; "
        "print(len(loaded))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "0", f"kernel stack imported eagerly: {result.stdout}"
