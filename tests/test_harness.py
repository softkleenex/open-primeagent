"""Harness - CRUD and rollback for H = (prompts, subagents, skills, memory)."""

from __future__ import annotations

import json

import pytest

from opa.harness.service import HarnessService
from opa.harness.state import STATE_FILE_NAME, HarnessStore
from opa.session import jsonl


@pytest.fixture
def harness(tmp_path):
    return HarnessService(tmp_path / "local", tmp_path / "global")


# ---------- store ----------

def test_file_layout_matches_the_original_schema(tmp_path):
    """An upstream prime-agent session must be readable as-is."""
    store = HarnessStore(tmp_path / STATE_FILE_NAME)
    store.create("prompt", "regenerate after migrations", "always run pnpm prisma generate")
    data = json.loads((tmp_path / STATE_FILE_NAME).read_text())

    assert data["schema"] == 1
    assert set(data["entries"]) == {"prompt", "memory", "skill", "subagent"}
    entry = next(iter(data["entries"]["prompt"].values()))
    assert {"id", "kind", "title", "content", "path", "scope", "version"} <= set(entry)


def test_reads_an_original_state_file(tmp_path):
    """Read a state file written by upstream."""
    (tmp_path / STATE_FILE_NAME).write_text(json.dumps({
        "schema": 1,
        "entries": {"memory": {"ports": {
            "id": "ports", "kind": "memory", "title": "ports", "content": "api=8080",
            "path": "general", "scope": "local", "source": "agent", "version": 3,
        }}},
        "refinements": [{"id": "ref-1", "trigger": "manual", "changes": ["x"]}],
    }), encoding="utf-8")
    store = HarnessStore(tmp_path / STATE_FILE_NAME)
    assert store.get("ports").version == 3
    assert store.refinements[0].id == "ref-1"


def test_corrupt_state_file_does_not_crash(tmp_path):
    (tmp_path / STATE_FILE_NAME).write_text("{not json", encoding="utf-8")
    store = HarnessStore(tmp_path / STATE_FILE_NAME)
    assert store.list() == []
    store.create("prompt", "t", "c")           # the next save rewrites it cleanly
    assert HarnessStore(tmp_path / STATE_FILE_NAME).list()[0].title == "t"


def test_non_ascii_titles_get_meaningful_ids(tmp_path):
    """Stripping non-ASCII would collapse every Korean title onto one fallback
    id, so ids would collide and mean nothing."""
    store = HarnessStore(tmp_path / STATE_FILE_NAME)
    assert store.create("memory", "서비스 포트", "api=8080").id == "서비스-포트"
    assert store.create("memory", "배포 절차", "x").id == "배포-절차"


def test_ids_are_slugged_and_unique(tmp_path):
    store = HarnessStore(tmp_path / STATE_FILE_NAME)
    a = store.create("prompt", "Run Prisma Generate!", "x")
    b = store.create("prompt", "Run Prisma Generate!", "y")
    assert a.id == "run-prisma-generate"
    assert b.id != a.id and b.id.startswith("run-prisma-generate-")


# ---------- scopes ----------

def test_local_and_global_are_separate_files(harness, tmp_path):
    harness.create("memory", "local note", "L")
    harness.create("memory", "global note", "G", global_=True)
    assert (tmp_path / "local" / STATE_FILE_NAME).exists()
    assert (tmp_path / "global" / STATE_FILE_NAME).exists()
    assert {e.title for e in harness.list()} == {"local note", "global note"}
    assert [e.title for e in harness.list(scope="global")] == ["global note"]


def test_overview_ids_can_be_fed_straight_back(harness):
    """If overview() prints [global:id], that exact string must be accepted back."""
    harness.create("prompt", "g", "content", global_=True)
    assert "[global:g]" in harness.overview()
    assert harness.update("global:g", content="updated").content == "updated"


# ---------- applying and reverting refinements ----------

def test_apply_records_a_reversible_event(harness):
    event = harness.apply(
        [{"op": "create", "kind": "prompt", "title": "always run tests", "content": "..."}],
        trigger="manual",
    )
    assert harness.get("always-run-tests") is not None
    harness.rollback(event.id)
    assert harness.get("always-run-tests") is None


def test_rollback_restores_the_previous_content(harness):
    harness.create("memory", "ports", "api=8080")
    event = harness.apply([{"op": "update", "id": "ports", "content": "api=9090"}], trigger="t")
    assert harness.get("ports").content == "api=9090"
    harness.rollback(event.id)
    assert harness.get("ports").content == "api=8080"


def test_rollback_restores_a_deleted_entry(harness):
    harness.create("skill", "migration check", "run generate", reference={"type": "python"})
    event = harness.apply([{"op": "delete", "id": "migration-check"}], trigger="t")
    assert harness.get("migration-check") is None
    harness.rollback(event.id)
    restored = harness.get("migration-check")
    assert restored.content == "run generate"
    assert restored.reference == {"type": "python"}


def test_a_failing_change_leaves_nothing_half_applied(harness):
    """A half-applied harness is the worst possible outcome."""
    with pytest.raises(KeyError):
        harness.apply(
            [
                {"op": "create", "kind": "prompt", "title": "good one", "content": "x"},
                {"op": "update", "id": "does-not-exist", "content": "y"},
            ],
            trigger="t",
        )
    assert harness.get("good-one") is None
    assert harness.list() == []


def test_rolling_back_twice_is_rejected(harness):
    event = harness.apply([{"op": "create", "kind": "prompt", "title": "t", "content": "c"}], trigger="x")
    harness.rollback(event.id)
    with pytest.raises(ValueError, match="already rolled back"):
        harness.rollback(event.id)


def test_unknown_op_is_rejected(harness):
    with pytest.raises(ValueError, match="unknown op"):
        harness.apply([{"op": "mutate", "id": "x"}], trigger="t")


# ---------- evidence gathering ----------

def test_evidence_counts_only_repeated_failures(harness, tmp_path):
    """A one-off is not promoted; only what recurred is."""
    trajectory = tmp_path / "trajectory.jsonl"
    for _ in range(3):
        jsonl.append(trajectory, {"event": "python.exec", "ok": False, "code": "import missing_mod"})
    jsonl.append(trajectory, {"event": "python.exec", "ok": False, "code": "one_off()"})
    jsonl.append(trajectory, {"event": "python.exec", "ok": True, "code": "fine()"})

    evidence = harness.evidence(trajectory)
    assert evidence["turns"] == 5
    assert evidence["failed_execs"] == 4
    assert evidence["repeated_errors"] == [{"signature": "import missing_mod", "count": 3}]
