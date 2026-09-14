"""Registry - does "a child is not disposable" survive a restart?"""

from __future__ import annotations

import pytest

from opa.rlm.registry import ChildRecord, ChildRegistry


@pytest.fixture
def registry(tmp_path):
    return ChildRegistry(tmp_path / "children").load()


def test_add_and_lookup_by_name_or_id(registry, tmp_path):
    record = registry.add(ChildRecord.new("api-reviewer", "claude-code", tmp_path))
    assert registry.get("api-reviewer") is record
    assert registry.get(record.rlm_child_id) is record
    assert registry.get("nope") is None


def test_survives_a_fresh_registry_instance(registry, tmp_path):
    """The same children must return after a host or kernel restart - the core requirement."""
    registry.add(ChildRecord.new("security", "claude-code", tmp_path, native_session_id="s-1"))
    registry.add(ChildRecord.new("backend", "codex", tmp_path))

    reloaded = ChildRegistry(tmp_path / "children").load()
    assert [r.name for r in reloaded.list()] == ["security", "backend"]
    assert reloaded.get("security").native_session_id == "s-1"


def test_duplicate_name_is_rejected_with_advice(registry, tmp_path):
    registry.add(ChildRecord.new("test", "claude-code", tmp_path))
    with pytest.raises(ValueError, match="Send it a message instead"):
        registry.add(ChildRecord.new("test", "claude-code", tmp_path))


def test_update_persists(registry, tmp_path):
    record = registry.add(ChildRecord.new("db", "claude-code", tmp_path))
    registry.update(record.rlm_child_id, status="completed", tokens=1234)
    reloaded = ChildRegistry(tmp_path / "children").load()
    assert reloaded.get("db").status == "completed"
    assert reloaded.get("db").tokens == 1234


def test_delete_is_explicit_and_names_alternatives(registry, tmp_path):
    registry.add(ChildRecord.new("frontend", "claude-code", tmp_path))
    with pytest.raises(KeyError, match="known: frontend"):
        registry.delete("backend")
    registry.delete("frontend")
    assert ChildRegistry(tmp_path / "children").load().list() == []


def test_corrupt_record_does_not_block_the_others(registry, tmp_path):
    registry.add(ChildRecord.new("good", "claude-code", tmp_path))
    broken = tmp_path / "children" / "opa-broken"
    broken.mkdir(parents=True)
    (broken / "child.json").write_text("{not json")
    assert [r.name for r in ChildRegistry(tmp_path / "children").load().list()] == ["good"]


def test_turns_are_appended(registry, tmp_path):
    record = registry.add(ChildRecord.new("t", "claude-code", tmp_path))
    registry.record_turn(record.rlm_child_id, {"prompt": "a"})
    registry.record_turn(record.rlm_child_id, {"prompt": "b"})
    assert [t["prompt"] for t in registry.turns(record.rlm_child_id)] == ["a", "b"]


def test_an_interrupted_turn_does_not_stay_running_forever(tmp_path):
    """A turn cannot outlive the process that awaited it.

    The task that would have run the `finally` dies with the server, so a record
    left at "running" claims work is in flight forever: `attention` says "still
    working" and points you at a report that can never arrive, and
    `list_subagents` reports a live `active_session_id`.
    """
    registry = ChildRegistry(tmp_path / "children")
    record = registry.add(
        ChildRecord.new("reviewer", "claude-code", tmp_path, native_session_id="sess-1")
    )
    registry.update(record.rlm_child_id, status="running")

    reborn = ChildRegistry(tmp_path / "children").load()
    recovered = reborn.get("reviewer")
    assert recovered.status == "error"
    assert "interrupted" in (recovered.last_error or "")
    assert recovered.native_session_id == "sess-1", "the child must stay re-taskable"


def test_reconciliation_is_written_down_not_just_computed(tmp_path):
    """Two restarts in a row must agree, and the second must not re-flag it."""
    registry = ChildRegistry(tmp_path / "children")
    record = registry.add(ChildRecord.new("worker", "claude-code", tmp_path))
    registry.update(record.rlm_child_id, status="running")

    first = ChildRegistry(tmp_path / "children").load().get("worker")
    second = ChildRegistry(tmp_path / "children").load().get("worker")
    assert first.status == second.status == "error"
    assert first.last_error == second.last_error


def test_a_finished_child_is_untouched_by_a_restart(tmp_path):
    registry = ChildRegistry(tmp_path / "children")
    for name, status in (("done", "completed"), ("failed", "error")):
        rec = registry.add(ChildRecord.new(name, "claude-code", tmp_path))
        registry.update(rec.rlm_child_id, status=status, last_error="original")

    reborn = ChildRegistry(tmp_path / "children").load()
    assert reborn.get("done").status == "completed"
    assert reborn.get("failed").last_error == "original", "an existing error must survive"
