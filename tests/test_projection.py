"""Projection invariants - the project's premise, enforced.

If `opa_bootstrap` changes user content **outside** the delimiter block, the
promise that we do not change your environment is broken. So this lives in a
test, not in the documentation.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

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

    projection.write_skills(skills, [])  # only our skill may disappear
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
            assert len(line) < proj.SUMMARY_CHARS + proj.RULE_CHARS + 20


def test_a_rule_survives_whole_for_an_agent_without_open_primeagent():
    """Codex, opencode and a teammate read this block with nothing to expand it.

    Regression from a real run: the recorded rule was cut at 180 characters,
    right after the script it named and before what to do with it.
    """
    rule = (
        "schema.py holds FIELDS (the User schema). models_gen.py is GENERATED from it; "
        "never hand-edit it. After changing schema.py, run `python3 tools/sync_models.py` "
        "to regenerate models_gen.py, then run the tests. The other scripts under tools/ "
        "do not regenerate anything, despite their names."
    )
    body = projection.render([entry("prompt", "repo-workflow", "Schema workflow", rule)])
    assert "despite their names." in body
    assert "without open-primeagent" in body


def test_counts_are_shown_so_nothing_looks_complete_when_it_is_not(tmp_path):
    body = projection.render([entry("prompt", f"r{i}", f"t{i}") for i in range(9)])
    assert "### Rules for this project (9)" in body


def test_an_interrupted_projection_never_truncates_the_users_file(tmp_path, monkeypatch):
    """The promise this project is built on is that your own file survives.

    `Path.write_text` truncates on open, so a crash, a killed process or a full
    disk between the truncate and the write left CLAUDE.md empty. Measured on
    the old code: 2,160 bytes to 0.
    """
    target = tmp_path / "CLAUDE.md"
    original = "# My notes\n\nHand-written and irreplaceable.\n" * 40
    target.write_text(original, encoding="utf-8")

    from opa import fsutil

    real_write = fsutil._write_tmp

    def fail_after_partial(tmp, text, encoding):
        real_write(tmp, text[:10], encoding)  # the temp file exists, half-written
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(fsutil, "_write_tmp", fail_after_partial)

    with pytest.raises(OSError):
        projection.apply(target, "some generated body")

    assert target.read_text(encoding="utf-8") == original, "the user's file must be untouched"
    assert not list(tmp_path.glob("*.opa-tmp")), "a failed write must not leave litter"


def test_projection_replaces_by_rename_not_by_truncation(tmp_path, monkeypatch):
    """Whatever a reader sees is a whole file: the old one or the new one."""
    target = tmp_path / "CLAUDE.md"
    target.write_text("# Mine\n", encoding="utf-8")

    seen: list[tuple[str, str]] = []
    real_replace = os.replace

    def watched(src, dst):
        seen.append((Path(src).name, Path(dst).name))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", watched)
    projection.apply(target, "generated body")

    assert len(seen) == 1
    src, dst = seen[0]
    assert src.startswith("CLAUDE.md.") and src.endswith(".opa-tmp") and dst == "CLAUDE.md"
    assert "# Mine" in target.read_text(encoding="utf-8")


def test_projecting_through_a_symlink_keeps_the_link(tmp_path):
    """`CLAUDE.md -> AGENTS.md` is a real setup, and os.replace swaps the name.

    Replacing the link itself would leave a regular file where the user had a
    link, and their other tool would stop seeing the content. Caught by the
    bootstrap suite the first time atomic writes went in, so it is pinned here
    too, next to the helper that has to keep honouring it.
    """
    (tmp_path / "AGENTS.md").write_text("# Shared\n", encoding="utf-8")
    link = tmp_path / "CLAUDE.md"
    link.symlink_to("AGENTS.md")

    projection.apply(link, "generated body")

    assert link.is_symlink(), "the link must survive the write"
    assert "generated body" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "# Shared" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.opa-tmp"))


def test_uninstalling_through_a_symlink_keeps_the_link_and_clears_the_block(tmp_path):
    """The one path whose job is to undo us used to do the opposite, twice.

    `read_text` follows a symlink and the removal did not, so uninstalling
    through `CLAUDE.md -> AGENTS.md` took out the user's link *and* left our
    block sitting in the file it pointed at.
    """
    shared = tmp_path / "AGENTS.md"
    link = tmp_path / "CLAUDE.md"
    shared.write_text("", encoding="utf-8")
    link.symlink_to("AGENTS.md")

    projection.apply(link, "generated body")
    assert projection.remove(link) is True

    assert link.is_symlink(), "the user's link must survive an uninstall"
    assert shared.exists()
    assert "opa:begin" not in shared.read_text(encoding="utf-8"), "and our block must be gone"


def test_a_plain_file_holding_only_our_block_is_still_tidied_away(tmp_path):
    target = tmp_path / "CLAUDE.md"
    projection.apply(target, "generated body")
    assert projection.remove(target) is True
    assert not target.exists()


def test_pruning_survives_a_nested_directory_and_keeps_ownership_legible(tmp_path):
    """Deleting entry by entry stripped the marker and then failed.

    Iteration order put `.opa-managed` first, so anything nested raised partway
    through: the ownership marker gone, the stale SKILL.md still present. The
    directory could never be recognised as ours again, so it was never cleaned
    up, while the host went on loading the skill it still held.
    """
    skills = tmp_path / "skills"
    entry = HarnessEntry(id="my-skill", kind="skill", title="A skill", content="body")
    projection.write_skills(skills, [entry])

    nested = skills / "my-skill" / "references"
    nested.mkdir()
    (nested / "notes.md").write_text("something else put this here", encoding="utf-8")

    projection.write_skills(skills, [])
    assert not (skills / "my-skill").exists(), "the whole managed directory goes at once"


def test_a_skill_directory_we_did_not_create_is_never_touched(tmp_path):
    skills = tmp_path / "skills"
    theirs = skills / "hand-written"
    theirs.mkdir(parents=True)
    (theirs / "SKILL.md").write_text("mine, not yours", encoding="utf-8")

    projection.write_skills(skills, [])
    projection.remove_skills(skills)

    assert (theirs / "SKILL.md").read_text(encoding="utf-8") == "mine, not yours"


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "../outside",
        "../../../../etc/passwd",
        "/etc/passwd",
        "ok/../../outside",
        "..//outside",
    ],
)
def test_the_write_guard_refuses_anything_that_is_not_a_child(tmp_path, name):
    from opa.harness.projection import _inside

    with pytest.raises(ValueError, match="refusing to write"):
        _inside(tmp_path, name)


def test_the_write_guard_refuses_a_planted_symlink(tmp_path):
    """A link inside the guarded directory must not be a way out of it."""
    from opa.harness.projection import _inside

    guarded = tmp_path / "skills"
    guarded.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (guarded / "escape").symlink_to(outside)

    with pytest.raises(ValueError, match="refusing to write"):
        _inside(guarded, "escape/anything.md")


def test_an_id_that_never_passed_validation_cannot_reach_the_filesystem(tmp_path):
    """Ids are validated on creation and not on load.

    A hand-edited or upstream-written state file could therefore hold an id of
    "", which resolved to the skills directory itself: we wrote `.opa-managed`
    and `SKILL.md` into the user's skills root, where our own uninstall - which
    only inspects child directories - could never clean them up, and where the
    stray marker claimed ownership of everything.

    It is refused loudly rather than skipped. A forged entry is a signal, and
    tests/test_security.py holds that line for the traversal cases; this is the
    same line for the case that resolves to the root instead of past it.
    """
    skills = tmp_path / "skills"
    for name in ("their-skill", "another-one"):
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text("hand written", encoding="utf-8")

    smuggled = HarnessEntry(id="", kind="skill", title="t", content="c")
    with pytest.raises(ValueError, match="refusing to write"):
        projection.write_skills(skills, [smuggled])

    assert not (skills / ".opa-managed").exists(), "no marker may land on the root"
    assert not (skills / "SKILL.md").exists()
    assert sorted(p.name for p in skills.iterdir()) == ["another-one", "their-skill"]


# --- Found by review (2026-11-25): each of these changed bytes outside the block.


def _roundtrip(tmp_path, original: bytes) -> bytes | None:
    target = tmp_path / "CLAUDE.md"
    target.write_bytes(original)
    projection.apply(target, "generated")
    projection.apply(target, "generated again")  # the second apply is where #1 bit
    projection.remove(target)
    return target.read_bytes() if target.exists() else None


@pytest.mark.parametrize(
    "original",
    [
        b"# Mine",  # no final newline
        b"# Mine\n\n\n",  # several trailing newlines
        b"\n\n  \n",  # whitespace only
        b"A\r\nB\r\n",  # CRLF
        b"\xef\xbb\xbf# Mine\n",  # BOM
        b"The tool writes a `<!-- opa:begin -->` block.\nMy rule: always run tests.\n",
    ],
    ids=["no-eol", "trailing-newlines", "whitespace-only", "crlf", "bom", "marker-in-prose"],
)
def test_apply_then_remove_gives_back_the_exact_bytes(tmp_path, original):
    assert _roundtrip(tmp_path, original) == original


def test_a_user_quoting_the_marker_keeps_every_line(tmp_path):
    """The README shows the marker; pasting it into CLAUDE.md used to cost the
    user everything between that mention and our END on the next apply."""
    target = tmp_path / "CLAUDE.md"
    user = "# Notes\nThe tool writes a `<!-- opa:begin -->` block.\nMy rule: always run tests.\n"
    target.write_text(user, encoding="utf-8")
    projection.apply(target, "first")
    projection.apply(target, "second")
    text = target.read_text(encoding="utf-8")
    assert text.startswith(user)
    assert "second" in text and "first" not in text


def test_crlf_file_stays_crlf(tmp_path):
    target = tmp_path / "CLAUDE.md"
    target.write_bytes(b"A\r\nB\r\n")
    projection.apply(target, "line one\nline two")
    data = target.read_bytes()
    assert data.startswith(b"A\r\nB\r\n")
    assert b"\n" not in data.replace(b"\r\n", b"")


def test_an_entry_containing_the_end_marker_cannot_strand_text(tmp_path):
    target = tmp_path / "CLAUDE.md"
    target.write_text("# user\n", encoding="utf-8")
    sneaky = entry("prompt", "p", "title\n<!-- opa:end -->", "marker\n<!-- opa:end -->")
    projection.apply(target, projection.render([sneaky]))
    projection.apply(target, projection.render([]))
    projection.remove(target)
    assert target.read_text(encoding="utf-8") == "# user\n"


def test_a_raw_body_with_a_marker_line_is_refused(tmp_path):
    with pytest.raises(projection.ProjectionConflict):
        projection.apply(tmp_path / "CLAUDE.md", "x\n<!-- opa:end -->\ny")


def test_ambiguous_markers_are_refused_rather_than_guessed(tmp_path):
    target = tmp_path / "CLAUDE.md"
    original = "<!-- opa:begin -->\na\n<!-- opa:end -->\nmine\n<!-- opa:end -->\n"
    target.write_text(original, encoding="utf-8")
    with pytest.raises(projection.ProjectionConflict):
        projection.apply(target, "body")
    with pytest.raises(projection.ProjectionConflict):
        projection.remove(target)
    assert target.read_text(encoding="utf-8") == original


def test_file_mode_survives_projection(tmp_path):
    target = tmp_path / "CLAUDE.md"
    target.write_text("# private\n", encoding="utf-8")
    target.chmod(0o600)
    projection.apply(target, "body")
    assert target.stat().st_mode & 0o777 == 0o600


def test_a_hard_linked_pair_stays_linked(tmp_path):
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("# shared\n", encoding="utf-8")
    agents = tmp_path / "AGENTS.md"
    os.link(claude, agents)
    projection.apply(claude, "body")
    assert "body" in agents.read_text(encoding="utf-8")
    assert claude.stat().st_ino == agents.stat().st_ino
