"""The kernel-facing API, exercised over a real socket with no kernel running.

`runtime_state` registers every handler the kernel can reach. Those handlers are
the validation boundary between model-generated Python and the host, so they get
tested directly rather than only through a live kernel.
"""

from __future__ import annotations

import pytest

from opa.runtime_state import Runtime
from opa_runtime.client import host_request


@pytest.fixture
async def runtime(config, monkeypatch):
    rt = Runtime(config)
    await rt.start_bridge()
    monkeypatch.setenv("OPA_HOST_SOCKET", str(rt.socket_path))
    yield rt
    await rt.shutdown()


# ---------- registration ----------

async def test_every_documented_type_is_registered(runtime):
    assert set(runtime.bridge.types) == {
        "agent_message.inbox",
        "agent_message.send",
        "harness.apply",
        "harness.create",
        "harness.delete",
        "harness.evidence",
        "harness.get",
        "harness.list",
        "harness.overview",
        "harness.project",
        "harness.refinements",
        "harness.rollback",
        "harness.update",
        "rlm.delete_subagent",
        "rlm.list_subagents",
        "rlm.run",
    }


# ---------- rlm ----------

async def test_rlm_run_requires_a_name(runtime):
    """`name` is the child's address for re-tasking, so a nameless child is useless."""
    with pytest.raises(RuntimeError, match="name= is required"):
        await host_request("rlm.run", {"prompt": "do something", "kwargs": {}})


async def test_rlm_run_requires_a_prompt(runtime):
    with pytest.raises(RuntimeError, match="prompt must be a non-empty string"):
        await host_request("rlm.run", {"prompt": "   ", "kwargs": {"name": "x"}})


async def test_list_subagents_is_empty_before_any_spawn(runtime):
    assert await host_request("rlm.list_subagents") == {"subagents": []}


async def test_delete_unknown_subagent_lists_what_exists(runtime):
    with pytest.raises(RuntimeError, match="no sub-agent matches"):
        await host_request("rlm.delete_subagent", {"target": "ghost"})


async def test_message_send_validates_its_arguments(runtime):
    with pytest.raises(RuntimeError, match="message must be a non-empty string"):
        await host_request("agent_message.send", {"message": "", "receiver_name": "a"})
    with pytest.raises(RuntimeError, match="receiver_name is required"):
        await host_request("agent_message.send", {"message": "hi"})


async def test_inbox_starts_empty(runtime):
    assert await host_request("agent_message.inbox") == {"messages": []}


# ---------- harness ----------

async def test_harness_crud_round_trip(runtime):
    created = await host_request(
        "harness.create",
        {"kind": "prompt", "title": "run generate", "content": "after migrations"},
    )
    entry_id = created["entry"]["id"]
    assert entry_id == "run-generate"

    assert (await host_request("harness.get", {"id": entry_id}))["entry"]["content"] == (
        "after migrations"
    )
    updated = await host_request("harness.update", {"id": entry_id, "content": "changed"})
    assert updated["entry"]["content"] == "changed"
    assert updated["entry"]["version"] == 2

    listed = await host_request("harness.list", {"kind": "prompt", "scope": "all"})
    assert [e["id"] for e in listed["entries"]] == [entry_id]

    await host_request("harness.delete", {"id": entry_id})
    assert (await host_request("harness.get", {"id": entry_id}))["entry"] is None


async def test_harness_create_rejects_unsafe_ids_over_the_bridge(runtime):
    """The traversal guard has to hold at the boundary the kernel actually calls."""
    with pytest.raises(RuntimeError, match="unsafe harness id"):
        await host_request(
            "harness.create",
            {"kind": "memory", "title": "t", "content": "c", "id": "../../CLAUDE"},
        )


async def test_harness_global_scope_is_addressable(runtime):
    await host_request(
        "harness.create",
        {"kind": "memory", "title": "shared", "content": "x", "global": True},
    )
    overview = (await host_request("harness.overview"))["overview"]
    assert "[global:shared]" in overview
    assert (await host_request("harness.get", {"id": "global:shared"}))["entry"] is not None


async def test_apply_then_rollback_over_the_bridge(runtime):
    event = (
        await host_request(
            "harness.apply",
            {
                "changes": [
                    {"op": "create", "kind": "prompt", "title": "note", "content": "body"}
                ],
                "trigger": "test",
            },
        )
    )["event"]
    assert (await host_request("harness.get", {"id": "note"}))["entry"] is not None

    await host_request("harness.rollback", {"event_id": event["id"]})
    assert (await host_request("harness.get", {"id": "note"}))["entry"] is None
    assert len((await host_request("harness.refinements"))["events"]) == 1


async def test_rollback_of_an_unknown_event_is_explained(runtime):
    with pytest.raises(RuntimeError, match="no refinement"):
        await host_request("harness.rollback", {"event_id": "ref-nope"})


async def test_evidence_reports_this_session(runtime):
    runtime.record("python.exec", {"ok": False, "code": "boom()"})
    runtime.record("python.exec", {"ok": False, "code": "boom()"})
    evidence = await host_request("harness.evidence")
    assert evidence["failed_execs"] == 2
    assert evidence["repeated_errors"] == [{"signature": "boom()", "count": 2}]


async def test_project_writes_only_inside_the_block(runtime, config):
    target = config.workspace / "CLAUDE.md"
    original = "# mine\n\n- a rule I wrote\n"
    target.write_text(original, encoding="utf-8")

    await host_request("harness.create", {"kind": "prompt", "title": "t", "content": "c"})
    await host_request("harness.project", {})
    assert original.rstrip("\n") in target.read_text(encoding="utf-8")

    await host_request("harness.project", {"remove": True})
    assert target.read_text(encoding="utf-8") == original
