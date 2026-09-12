"""Pins the parts of prime-agent's `rlm` API that we claim to inherit.

We are an independent reimplementation, not a fork, so nothing here is copied
code. What is reproduced is a *contract*: the field names, the closed status set
and the payload keys that upstream's runtime validates. Code written against
prime-agent has to keep working against us, and the only way to keep that true
is to fail a test when it stops being true.

Transcribed from, and citations point at, the read-only reference checkout:

    _ref/prime-agent/prime-agent-runtime/src/rlm/__init__.py
    _ref/prime-agent/prime-agent-runtime/src/rlm/harness.py

`_ref/` is deliberately not committed, so the contract lives here as data
instead of being imported. If upstream changes it, this file is what has to be
re-checked by hand against a fresh reference read.

Where we deviate on purpose, the deviation is asserted too - a documented
divergence is a decision, an undocumented one is a bug.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from opa.rlm.registry import ChildRecord, ChildStatus
from opa.runtime_state import Runtime
from opa_runtime import client
from opa_runtime.client import host_request
from opa_runtime.rlm import RLMSpawnHandle, RLMSubagent

# ---------- upstream's contract, transcribed ----------

# rlm/__init__.py:44 class RLMSubagent
UPSTREAM_SUBAGENT_FIELDS = (
    "rlm_child_id",
    "active_session_id",
    "session_id",
    "session_name",
    "session_dir",
    "status",
)
# rlm/__init__.py:200  if status not in {...}
UPSTREAM_STATUSES = frozenset({"running", "completed", "error"})
# rlm/__init__.py:28 class RLMSpawnHandle
UPSTREAM_HANDLE_FIELDS = ("rlm_child_id", "session_dir", "status", "model")
# rlm/__init__.py:317 __all__
UPSTREAM_RLM_CALLABLES = ("run", "list_subagents", "delete_subagent")
# What upstream's own shipped skills call, extracted from
# packages/coding-agent/skills/*/SKILL.md. This is a sharper test than the
# module's __all__: these are the calls that upstream documentation tells a
# model to make, so a missing one breaks a skill a user may paste in verbatim.
UPSTREAM_SKILL_CALLS = {
    "goal": ("get", "create", "complete"),
    "rlm": ("list_subagents", "delete_subagent"),
    "agent_message": ("send", "list_agents"),
}
# Deliberately not provided. Recorded so the omission stays a decision.
#   rlm_heartbeat.*  - our equivalent is `schedule`, under a different name
#   compact.*, refine.*, linear.*, notion.*, agent_observe.*
#                    - host-harness features we delegate rather than reimplement
UPSTREAM_SKILL_CALLS_NOT_PROVIDED = ("rlm_heartbeat", "compact", "refine", "agent_observe")

# rlm/harness.py HarnessEntry
UPSTREAM_HARNESS_ENTRY_FIELDS = (
    "id",
    "kind",
    "title",
    "content",
    "path",
    "scope",
    "reference",
    "arguments",
    "metadata",
    "source",
    "created_at",
    "updated_at",
    "version",
)


@pytest.fixture
async def runtime(config, monkeypatch):
    rt = Runtime(config)
    await rt.start_bridge()
    monkeypatch.setenv("OPA_HOST_SOCKET", str(rt.socket_path))
    client.set_token(rt.kernel_token)
    yield rt
    client.set_token(None)
    await rt.shutdown()


def _assert_upstream_accepts(payload: dict, operation: str) -> None:
    """Reproduces upstream's `_subagent_from_payload` acceptance rules.

    rlm/__init__.py:181. Upstream *raises* on a payload that fails any of
    these, so a payload failing here is one upstream-written code cannot read.
    """
    assert isinstance(payload, dict), f"{operation} must return a dict"
    child_id = payload.get("rlm_child_id")
    assert isinstance(child_id, str) and child_id, f"{operation}: rlm_child_id"
    for key in ("active_session_id", "session_id"):
        value = payload.get(key)
        assert value is None or isinstance(value, str), f"{operation}: {key}"
    name = payload.get("session_name")
    assert isinstance(name, str) and name, f"{operation}: session_name"
    directory = payload.get("session_dir")
    assert isinstance(directory, str) and directory, f"{operation}: session_dir"
    assert payload.get("status") in UPSTREAM_STATUSES, f"{operation}: status"


# ---------- the inherited surface exists ----------

def test_subagent_carries_every_upstream_field():
    """Upstream code reading `.session_id` must not hit an AttributeError."""
    ours = {f.name for f in fields(RLMSubagent)}
    missing = [f for f in UPSTREAM_SUBAGENT_FIELDS if f not in ours]
    assert not missing, f"RLMSubagent lost upstream fields: {missing}"


def test_spawn_handle_carries_every_upstream_field():
    ours = {f.name for f in fields(RLMSpawnHandle)}
    missing = [f for f in UPSTREAM_HANDLE_FIELDS if f not in ours]
    assert not missing, f"RLMSpawnHandle lost upstream fields: {missing}"


def test_harness_entry_matches_upstream_field_for_field():
    """The state file is the interop surface, so its record shape is exact.

    Not a superset: an extra field would be written into a file upstream also
    reads, and we promise that file stays upstream-compatible.
    """
    from opa.harness.state import HarnessEntry

    assert {f.name for f in fields(HarnessEntry)} == set(UPSTREAM_HARNESS_ENTRY_FIELDS)


def test_status_vocabulary_is_exactly_upstreams():
    """A status outside this set makes upstream's validator raise, not warn."""
    assert set(ChildStatus.__args__) == UPSTREAM_STATUSES


def test_rlm_exposes_upstreams_callables():
    from opa_runtime.rlm import rlm

    for name in UPSTREAM_RLM_CALLABLES:
        assert callable(getattr(rlm, name, None)), f"rlm.{name} is missing"


def test_upstream_skills_find_the_calls_they_document():
    """Upstream's shipped skills should run here, not just its type names.

    Found `agent_message.list_agents` missing this way: it is documented in
    upstream's agent-message skill, so a user pasting that skill in would have
    hit an AttributeError before sending anything.
    """
    from opa_runtime import agent_message, goal
    from opa_runtime.rlm import rlm

    objects = {"goal": goal, "rlm": rlm, "agent_message": agent_message}
    missing = [
        f"{obj}.{call}"
        for obj, calls in UPSTREAM_SKILL_CALLS.items()
        for call in calls
        if not callable(getattr(objects[obj], call, None))
    ]
    assert not missing, f"upstream skills call these and we do not have them: {missing}"


def test_upstream_request_type_names_are_registered(runtime):
    """Same names on the wire, so a port is a transport swap and not a rewrite."""
    for name in UPSTREAM_RLM_CALLABLES:
        assert f"rlm.{name}" in runtime.bridge.types


# ---------- the inherited wire shapes validate ----------

async def test_list_subagents_entries_pass_upstreams_validator(runtime):
    runtime.rlm.registry.add(
        ChildRecord.new(
            "reviewer",
            "claude-code",
            Path(runtime.config.workspace),
            native_session_id="sess-1",
        )
    )
    payload = await host_request("rlm.list_subagents")
    assert payload["subagents"], "expected the registered child back"
    for entry in payload["subagents"]:
        _assert_upstream_accepts(entry, "rlm.list_subagents")


async def test_delete_subagent_returns_a_full_record_under_the_upstream_key(runtime):
    """Regression: we used to answer `{"deleted": {id, name}}`.

    Upstream reads `payload["subagent"]` and validates it as a whole record, so
    that shape made an identically named request unreadable to upstream code.
    """
    runtime.rlm.registry.add(
        ChildRecord.new(
            "doomed",
            "claude-code",
            Path(runtime.config.workspace),
            native_session_id="sess-2",
        )
    )
    payload = await host_request("rlm.delete_subagent", {"target": "doomed"})
    assert "subagent" in payload, "upstream reads the 'subagent' key"
    _assert_upstream_accepts(payload["subagent"], "rlm.delete_subagent")


async def test_active_session_id_is_none_once_a_child_is_idle(runtime):
    """The distinction upstream draws that a bare `status` cannot express.

    `session_id` says the child has a session to resume; `active_session_id`
    says a turn is in flight right now.
    """
    record = runtime.rlm.registry.add(
        ChildRecord.new(
            "worker",
            "claude-code",
            Path(runtime.config.workspace),
            native_session_id="sess-3",
        )
    )
    running = (await host_request("rlm.list_subagents"))["subagents"][0]
    assert running["active_session_id"] == "sess-3"

    record.status = "completed"
    idle = (await host_request("rlm.list_subagents"))["subagents"][0]
    assert idle["session_id"] == "sess-3", "the session is still resumable"
    assert idle["active_session_id"] is None, "but nothing is running in it"


# ---------- deliberate divergence ----------

def test_we_add_fields_upstream_does_not_have():
    """Our extras are additive, which is why upstream code still parses ours.

    Recorded so that removing one is a visible decision: the counters are what
    `attention()` and the goal budget are computed from.
    """
    ours = {f.name for f in fields(RLMSubagent)}
    for extra in ("turns", "tokens", "cost_usd", "adapter", "last_error"):
        assert extra in ours


def test_we_can_read_a_payload_in_upstreams_own_shape():
    """Compatibility has to run both ways, or it is not a shared protocol.

    Our parser required `name`, `adapter` and the three counters - all fields
    upstream does not send - so a record in exactly the shape upstream produces
    raised `KeyError: 'name'` while the README claimed we spoke its protocol.
    """
    from opa_runtime.rlm import _subagent

    upstream_shaped = {
        "rlm_child_id": "c-1",
        "active_session_id": None,
        "session_id": "s-1",
        "session_name": "reviewer",
        "session_dir": "/tmp/x",
        "status": "completed",
    }
    got = _subagent(upstream_shaped)
    assert got.rlm_child_id == "c-1"
    assert got.session_name == "reviewer"
    assert got.name == "reviewer", "our own field falls back to upstream's"
    assert got.session_id == "s-1"
    assert got.turns == 0 and got.cost_usd == 0.0, "our extras default, not explode"
