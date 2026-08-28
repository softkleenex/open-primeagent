"""Projection invariants - the project's premise, enforced.

If `opa_bootstrap` changes user content **outside** the delimiter block, the
promise that we do not change your environment is broken. So this lives in a
test, not in the documentation.
"""

from __future__ import annotations

from opa.harness import projection
from opa.harness.state import HarnessEntry

USER_FILE = """# My Project

Project rules:
- write commit messages in Korean
- no merge without tests

<!-- a comment the user wrote themselves -->
done.
"""


def entry(kind, id, title, content="body text"):
    return HarnessEntry(id=id, kind=kind, title=title, content=content)


def test_apply_preserves_content_outside_block(tmp_path):
    """Content outside the block is preserved byte for byte."""
    target = tmp_path / "CLAUDE.md"
    target.write_text(USER_FILE, encoding="utf-8")

    projection.apply(target, "first version")
    after = target.read_text(encoding="utf-8")

    assert USER_FILE.rstrip("\n") in after
    assert "first version" in after

    # the user's content must survive a second application too
    projection.apply(target, "second version")
    after2 = target.read_text(encoding="utf-8")
    assert USER_FILE.rstrip("\n") in after2
    assert "first version" not in after2
    assert "second version" in after2


def test_remove_restores_original_file(tmp_path):
    """After remove the file is byte-identical to the original."""
    target = tmp_path / "AGENTS.md"
    target.write_text(USER_FILE, encoding="utf-8")

    projection.apply(target, "some projection")
    assert projection.remove(target) is True
    assert target.read_text(encoding="utf-8") == USER_FILE


def test_apply_is_idempotent(tmp_path):
    """Applying the same body twice leaves the file unchanged."""
    target = tmp_path / "CLAUDE.md"
    target.write_text(USER_FILE, encoding="utf-8")

    projection.apply(target, "stable body")
    once = target.read_text(encoding="utf-8")
    assert projection.apply(target, "stable body") is False
    assert target.read_text(encoding="utf-8") == once


def test_block_only_file_is_deleted_on_remove(tmp_path):
    """If we created the file, leave no trace behind."""
    target = tmp_path / "CLAUDE.md"
    projection.apply(target, "body")
    assert target.exists()
    projection.remove(target)
    assert not target.exists()


def test_remove_on_untouched_file_changes_nothing(tmp_path):
    target = tmp_path / "CLAUDE.md"
    target.write_text(USER_FILE, encoding="utf-8")
    assert projection.remove(target) is False
    assert target.read_text(encoding="utf-8") == USER_FILE


def test_render_puts_only_the_index_for_memories(tmp_path):
    """Memory bodies never enter the block - context is not a warehouse."""
    entries = [
        entry("prompt", "migration", "run prisma generate after a migration"),
        entry("memory", "ports", "port list", content="a very long body " * 200),
    ]
    body = projection.render(entries, memory_dir=tmp_path)
    assert "run prisma generate after a migration" in body
    assert "`.opa/memory/ports.md`" in body
    assert "a very long body a very long body" not in body


def test_write_memories_creates_and_prunes(tmp_path):
    memory_dir = tmp_path / "memory"
    projection.write_memories(memory_dir, [entry("memory", "a", "A"), entry("memory", "b", "B")])
    assert {p.stem for p in memory_dir.glob("*.md")} == {"a", "b"}

    projection.write_memories(memory_dir, [entry("memory", "a", "A")])
    assert {p.stem for p in memory_dir.glob("*.md")} == {"a"}


def test_write_skills_never_touches_user_skills(tmp_path):
    """Deleting a skill the user wrote themselves would break the promise."""
    skills = tmp_path / "skills"
    user_skill = skills / "my-own"
    user_skill.mkdir(parents=True)
    (user_skill / "SKILL.md").write_text("mine", encoding="utf-8")

    projection.write_skills(skills, [entry("skill", "opa-one", "One")])
    assert (skills / "opa-one" / "SKILL.md").exists()

    projection.write_skills(skills, [])           # only our skill may disappear
    assert not (skills / "opa-one").exists()
    assert (user_skill / "SKILL.md").read_text() == "mine"

    projection.remove_skills(skills)
    assert (user_skill / "SKILL.md").read_text() == "mine"


def test_apply_finds_a_block_written_with_a_different_marker_text(tmp_path):
    """A changed marker wording must still be found and replaced.
    Otherwise a fresh block piles up on every run."""
    target = tmp_path / "CLAUDE.md"
    target.write_text(
        "keep me\n\n<!-- opa:begin (old wording) -->\nold body\n<!-- opa:end -->\n",
        encoding="utf-8",
    )
    projection.apply(target, "new body")
    text = target.read_text(encoding="utf-8")
    assert text.count("opa:begin") == 1
    assert "old body" not in text
    assert "keep me" in text


def test_the_block_is_budgeted_because_it_is_read_every_request(tmp_path):
    """Unbounded, this block would grow until it cost more than it saved."""
    from opa.harness import projection as proj

    long_body = "SENTINEL_HEAD " + ("filler " * 200) + "SENTINEL_TAIL"
    many = [entry("prompt", f"rule-{i}", f"Rule number {i}", long_body) for i in range(20)]
    body = proj.render(many)

    assert body.count("- **") == proj.MAX_PER_KIND
    assert "14 more" in body
    assert "harness.overview()" in body
    # a summary, not the entry: the head survives, the rest does not
    assert "SENTINEL_HEAD" in body
    assert "SENTINEL_TAIL" not in body
    for line in body.splitlines():
        if line.startswith("- **"):
            assert len(line) < proj.SUMMARY_CHARS + 60


def test_counts_are_shown_so_nothing_looks_complete_when_it_is_not(tmp_path):
    body = projection.render([entry("prompt", f"r{i}", f"t{i}") for i in range(9)])
    assert "### Rules for this project (9)" in body
