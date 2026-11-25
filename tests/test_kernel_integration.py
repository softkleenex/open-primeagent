"""L1 - boots a real kernel. These are the ROADMAP Phase 1 exit criteria.

Marked slow so they can be excluded with `-m "not slow"`.
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
    """IPython autoawait handles it; nest_asyncio is unnecessary."""
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
    """rlm is a kernel symbol, not an MCP tool."""
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


async def test_status_reports_what_is_still_callable(server):
    """After a host loses context, the useful fact is not what was stored but
    what still exists in the kernel."""
    await call(server, "opa_python", {"code": "files = [1, 2, 3]\ndef rank(x): return x"})
    state = json.loads(await call(server, "opa_status", {}))
    assert "files" in state["kernel_names"]
    assert "rank" in state["kernel_names"]
    assert "In" not in state["kernel_names"]


async def test_asking_for_names_does_not_start_a_kernel(server):
    state = json.loads(await call(server, "opa_status", {}))
    assert state["kernel_names"] == []
    assert server._opa_runtime.kernel_if_started is None


async def test_the_name_list_leaves_out_what_is_always_there(server):
    """The list exists to re-orient a caller that lost context. Preloaded symbols
    are present in every kernel, so naming them crowds out the few names that
    actually say what this session built."""
    await call(server, "opa_python", {"code": "dependency_graph = {'a': ['b']}"})
    state = json.loads(await call(server, "opa_status", {}))

    assert "dependency_graph" in state["kernel_names"]
    for always_there in ("rlm", "harness", "goal", "schedule", "agent_message"):
        assert always_there not in state["kernel_names"]


# --- Found by review (2026-11-25)


async def test_concurrent_calls_do_not_steal_each_others_output(server):
    """Two cells running at once both read the one iopub stream and each threw
    away the other's messages. Measured: a status call came back empty and a
    15s-timeout cell was still hung after 30s."""
    import asyncio

    await call(server, "opa_python", {"code": "kept = 1"})
    await call(server, "opa_status", {})  # while busy, status answers from the last list
    slow = asyncio.create_task(
        call(server, "opa_python", {"code": "import time; time.sleep(1); print('SLOW-DONE')", "timeout": 15})
    )
    await asyncio.sleep(0.2)
    fast, status = await asyncio.wait_for(
        asyncio.gather(
            call(server, "opa_python", {"code": "print('FAST-DONE')"}),
            call(server, "opa_status", {}),
        ),
        timeout=20,
    )
    assert "SLOW-DONE" in await asyncio.wait_for(slow, timeout=20)
    assert "FAST-DONE" in fast
    assert "kept" in status


async def test_a_failed_boot_does_not_leak_the_kernel(config, monkeypatch):
    from opa.kernel.manager import KernelManager

    started: list[KernelManager] = []
    real_start = KernelManager.start

    async def boot_then_fail(self):
        started.append(self)
        real_bootstrap = self._bootstrap
        self._bootstrap = lambda: real_bootstrap() + "\nraise SystemExit"
        async def failing_execute(*a, **k):
            raise RuntimeError("bootstrap blew up")
        monkeypatch.setattr(self, "execute", failing_execute)
        await real_start(self)

    monkeypatch.setattr(KernelManager, "start", boot_then_fail)
    srv = build_server(config)
    try:
        with pytest.raises(RuntimeError, match="bootstrap blew up"):
            await srv._opa_runtime.kernel()
        assert started and started[0]._km is None, "the half-started kernel was left running"
    finally:
        await srv._opa_runtime.shutdown()
