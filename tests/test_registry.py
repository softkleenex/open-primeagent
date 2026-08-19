"""registry — "child는 일회용이 아니다"가 재시작을 넘어 성립하는지."""

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
    """호스트/커널이 재시작해도 같은 child가 나와야 한다 — 이게 핵심 요구사항이다."""
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
