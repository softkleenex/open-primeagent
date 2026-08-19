"""Harness — H = (prompts, subagents, skills, memory) 의 CRUD와 되돌리기."""

from __future__ import annotations

import json

import pytest

from opa.harness.service import HarnessService
from opa.harness.state import STATE_FILE_NAME, HarnessStore
from opa.session import jsonl


@pytest.fixture
def harness(tmp_path):
    return HarnessService(tmp_path / "local", tmp_path / "global")


# ---------- 스토어 ----------

def test_file_layout_matches_the_original_schema(tmp_path):
    """원본 prime-agent 세션을 그대로 읽을 수 있어야 한다."""
    store = HarnessStore(tmp_path / STATE_FILE_NAME)
    store.create("prompt", "migration 후 generate", "pnpm prisma generate 를 반드시 실행")
    data = json.loads((tmp_path / STATE_FILE_NAME).read_text())

    assert data["schema"] == 1
    assert set(data["entries"]) == {"prompt", "memory", "skill", "subagent"}
    entry = next(iter(data["entries"]["prompt"].values()))
    assert {"id", "kind", "title", "content", "path", "scope", "version"} <= set(entry)


def test_reads_an_original_state_file(tmp_path):
    """원본이 쓴 파일을 그대로 읽는다."""
    (tmp_path / STATE_FILE_NAME).write_text(json.dumps({
        "schema": 1,
        "entries": {"memory": {"ports": {
            "id": "ports", "kind": "memory", "title": "포트", "content": "api=8080",
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
    store.create("prompt", "t", "c")           # 다음 save가 깨끗이 다시 쓴다
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


# ---------- 스코프 ----------

def test_local_and_global_are_separate_files(harness, tmp_path):
    harness.create("memory", "local note", "L")
    harness.create("memory", "global note", "G", global_=True)
    assert (tmp_path / "local" / STATE_FILE_NAME).exists()
    assert (tmp_path / "global" / STATE_FILE_NAME).exists()
    assert {e.title for e in harness.list()} == {"local note", "global note"}
    assert [e.title for e in harness.list(scope="global")] == ["global note"]


def test_overview_ids_can_be_fed_straight_back(harness):
    """overview()가 [global:id] 로 보여주면 그 문자열이 그대로 통해야 한다."""
    harness.create("prompt", "g", "content", global_=True)
    assert "[global:g]" in harness.overview()
    assert harness.update("global:g", content="updated").content == "updated"


# ---------- 개선 적용/되돌리기 ----------

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
    """반쪽만 적용된 harness가 남는 게 제일 나쁘다."""
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


# ---------- 근거 수집 ----------

def test_evidence_counts_only_repeated_failures(harness, tmp_path):
    """한 번 겪은 일은 승격하지 않는다 — 반복된 것만 올린다."""
    trajectory = tmp_path / "trajectory.jsonl"
    for _ in range(3):
        jsonl.append(trajectory, {"event": "python.exec", "ok": False, "code": "import missing_mod"})
    jsonl.append(trajectory, {"event": "python.exec", "ok": False, "code": "one_off()"})
    jsonl.append(trajectory, {"event": "python.exec", "ok": True, "code": "fine()"})

    evidence = harness.evidence(trajectory)
    assert evidence["turns"] == 5
    assert evidence["failed_execs"] == 4
    assert evidence["repeated_errors"] == [{"signature": "import missing_mod", "count": 3}]
