"""L0 - does everything that must survive a restart actually reach the disk?"""

from __future__ import annotations

from opa.session import jsonl
from opa.session.paths import SessionPaths


def test_ensure_creates_every_directory(tmp_path):
    paths = SessionPaths(root=tmp_path, session_id="s1").ensure()
    for directory in (paths.dir, paths.outputs, paths.mailbox, paths.children):
        assert directory.is_dir()
    assert paths.harness_state.parent.is_dir()


def test_jsonl_roundtrip_keeps_unicode(tmp_path):
    path = tmp_path / "t.jsonl"
    jsonl.append(path, {"k": "한글", "n": 1})
    jsonl.append(path, {"k": "b", "n": 2})
    assert list(jsonl.read(path)) == [{"k": "한글", "n": 1}, {"k": "b", "n": 2}]
    assert jsonl.count(path) == 2


def test_jsonl_skips_corrupt_lines(tmp_path):
    """Progress beats completeness: one corrupt line must not block the rest."""
    path = tmp_path / "t.jsonl"
    jsonl.append(path, {"n": 1})
    path.open("a").write("{not json\n")
    jsonl.append(path, {"n": 2})
    assert [r["n"] for r in jsonl.read(path)] == [1, 2]


def test_jsonl_read_missing_file_is_empty(tmp_path):
    assert list(jsonl.read(tmp_path / "nope.jsonl")) == []
