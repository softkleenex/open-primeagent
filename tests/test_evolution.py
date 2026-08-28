"""Phase 5 - changing what the host agent reads, mid-session.

The measured claim behind this
(docs/concepts/evolution.md section 1.2) is that a server can replace its own
tool description, send `tools/list_changed`, and have the host act on the new
text from the next turn. These tests cover our side of that.
"""

from __future__ import annotations

import pytest

from opa.harness.state import HarnessEntry
from opa.runtime_state import Runtime
from opa.tools.surface import ToolSurface
from opa_runtime.client import host_request

BASE = "Execute Python in a persistent kernel."


def entry(title: str, content: str = "body", kind: str = "prompt") -> HarnessEntry:
    return HarnessEntry(id=title.lower().replace(" ", "-"), kind=kind, title=title,
                        content=content)


class FakeServer:
    def __init__(self) -> None:
        self.registered: list[tuple[str, str]] = []

    def remove_tool(self, name):
        self.registered = [r for r in self.registered if r[0] != name]

    def add_tool(self, fn, name=None, description=None):
        self.registered.append((name, description))


class FakeConnection:
    def __init__(self) -> None:
        self.notifications = 0

    async def send_tool_list_changed(self):
        self.notifications += 1


class DeadConnection:
    async def send_tool_list_changed(self):
        raise ConnectionResetError("host went away")


# ---------- rendering ----------

def test_an_empty_harness_leaves_the_description_alone():
    surface = ToolSurface(FakeServer(), "opa_python", BASE)
    assert surface.render([]) == BASE


def test_the_description_lists_notes_without_repeating_their_instructions():
    """Unattributed imperatives from a server are treated as injection - correctly.
    So the description carries an index and says where to read the real text."""
    surface = ToolSurface(FakeServer(), "opa_python", BASE)
    text = surface.render([entry("regenerate after migrations", "run tools/sync_models.py")])
    assert BASE.strip() in text
    assert "regenerate after migrations" in text          # the title, so it is findable
    assert "run tools/sync_models.py" not in text          # not the instruction itself
    assert "harness.overview()" in text                    # where to read it


def test_entries_are_attributed():
    surface = ToolSurface(FakeServer(), "opa_python", BASE)
    text = surface.render([entry("a rule")])
    assert "recorded by" in text


def test_only_prompt_entries_reach_the_description():
    """Memory bodies belong in files, not in every request."""
    surface = ToolSurface(FakeServer(), "opa_python", BASE)
    text = surface.render([entry("a port", "api=8080", kind="memory")])
    assert text == BASE


def test_a_long_note_body_never_reaches_the_description():
    surface = ToolSurface(FakeServer(), "opa_python", BASE)
    text = surface.render([entry("wordy", "x" * 5000)])
    assert len(text) < 1000
    assert "xxxx" not in text


def test_the_description_does_not_grow_without_bound():
    surface = ToolSurface(FakeServer(), "opa_python", BASE)
    text = surface.render([entry(f"rule {i}") for i in range(40)])
    assert "and 28 more" in text


# ---------- refresh ----------

async def test_refresh_reregisters_the_tool_and_notifies():
    server, connection = FakeServer(), FakeConnection()
    surface = ToolSurface(server, "opa_python", BASE)
    surface.bind(lambda code: code)

    assert await surface.refresh([entry("always run tests")], connection) is True
    assert server.registered[-1][0] == "opa_python"
    assert "always run tests" in server.registered[-1][1]
    assert connection.notifications == 1


async def test_refresh_is_a_no_op_when_nothing_changed():
    connection = FakeConnection()
    surface = ToolSurface(FakeServer(), "opa_python", BASE)
    surface.bind(lambda code: code)
    entries = [entry("stable")]

    assert await surface.refresh(entries, connection) is True
    assert await surface.refresh(entries, connection) is False
    assert connection.notifications == 1


async def test_a_departed_host_does_not_break_evolution():
    """The text still changes; a host that ignores the notification picks it up
    on its next tools/list."""
    surface = ToolSurface(FakeServer(), "opa_python", BASE)
    surface.bind(lambda code: code)
    assert await surface.refresh([entry("x")], DeadConnection()) is True


async def test_binding_is_required():
    surface = ToolSurface(FakeServer(), "opa_python", BASE)
    with pytest.raises(RuntimeError, match="bind"):
        await surface.refresh([entry("x")])


# ---------- through the bridge ----------

@pytest.fixture
async def runtime(config, monkeypatch):
    rt = Runtime(config)
    rt.surface = ToolSurface(FakeServer(), "opa_python", BASE)
    rt.surface.bind(lambda code: code)
    rt.connection = FakeConnection()
    await rt.start_bridge()
    monkeypatch.setenv("OPA_HOST_SOCKET", str(rt.socket_path))
    yield rt
    await rt.shutdown()


async def test_creating_a_prompt_entry_changes_what_the_host_reads(runtime):
    await host_request(
        "harness.create",
        {"kind": "prompt", "title": "run generate", "content": "after migrations"},
    )
    surface = await host_request("harness.surface")
    assert "run generate" in surface["description"]
    assert runtime.connection.notifications == 1


async def test_only_unprojected_entries_are_repeated(runtime):
    """Once a rule is in the file the host reads, repeating it in the
    description bills the same text twice."""
    already = runtime.harness.create("prompt", "already in the file", "old rule")
    already.metadata["projected_at"] = "2999-01-01T00:00:00+00:00"
    runtime.harness.local.save()

    await host_request(
        "harness.create", {"kind": "prompt", "title": "not yet", "content": "new rule"}
    )
    surface = await host_request("harness.surface")
    assert "not yet" in surface["description"]
    assert "already in the file" not in surface["description"]


async def test_projection_stops_the_description_repeating_a_rule(runtime, config):
    """The two layers hand over: once projection delivers, the surface drops it."""
    (config.workspace / "CLAUDE.md").write_text("# mine\n", encoding="utf-8")
    await host_request(
        "harness.create", {"kind": "prompt", "title": "handover", "content": "a rule"}
    )
    assert "handover" in (await host_request("harness.surface"))["description"]

    await host_request("harness.project", {})
    await runtime.refresh_surface()
    assert "handover" not in (await host_request("harness.surface"))["description"]
    assert "handover" in (config.workspace / "CLAUDE.md").read_text(encoding="utf-8")


async def test_a_restart_stops_carrying_notes_it_cannot_remember_making(runtime, config):
    """Measured: a host asked to quote a note recorded before it started replies
    that it has no record of creating it and treats it as possible injection.
    No wording fixes that, so a fresh process carries nothing and the note
    reaches the agent through the project file instead."""
    await host_request(
        "harness.create", {"kind": "prompt", "title": "from before", "content": "x"}
    )
    from opa.server import build_server

    revived = build_server(config)
    try:
        assert "from before" not in revived._opa_runtime.surface.current_description
        # still in the harness, and still reachable when the agent asks
        assert revived._opa_runtime.harness.get("from-before") is not None
    finally:
        await revived._opa_runtime.shutdown()


async def test_notes_from_an_earlier_session_are_not_repeated(runtime):
    older = runtime.harness.create("prompt", "last week", "x")
    older.updated_at = "2020-01-01T00:00:00+00:00"
    runtime.harness.local.save()
    await runtime.refresh_surface()
    assert "last week" not in (await host_request("harness.surface"))["description"]


async def test_evolve_reports_which_layers_it_reached(runtime, config):
    (config.workspace / "CLAUDE.md").write_text("# mine\n", encoding="utf-8")
    result = await host_request(
        "harness.evolve",
        {
            "changes": [
                {"op": "create", "kind": "prompt", "title": "check migrations",
                 "content": "run tools/sync_models.py after schema edits"},
            ],
            "trigger": "/evolve",
        },
    )
    assert result["applied"] == {"next_turn": True, "next_session": True}
    assert "check migrations" in (config.workspace / "CLAUDE.md").read_text(encoding="utf-8")
    # projection delivered it, so the description hands over and stops repeating
    assert "check migrations" not in (await host_request("harness.surface"))["description"]


async def test_evolve_is_reversible(runtime):
    result = await host_request(
        "harness.evolve",
        {"changes": [{"op": "create", "kind": "prompt", "title": "temp", "content": "x"}]},
    )
    await host_request("harness.rollback", {"event_id": result["event"]["id"]})
    assert "temp" not in (await host_request("harness.surface"))["description"]


async def test_evolve_can_skip_the_file_projection(runtime, config):
    result = await host_request(
        "harness.evolve",
        {
            "changes": [{"op": "create", "kind": "prompt", "title": "t", "content": "c"}],
            "project": False,
        },
    )
    assert result["applied"]["next_turn"] is True
    assert result["applied"]["next_session"] is False
    assert not (config.workspace / "AGENTS.md").exists()
