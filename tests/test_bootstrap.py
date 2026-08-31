"""opa_bootstrap — the promise "we don't change your environment" lives or dies here."""

from __future__ import annotations

import pytest

from opa.harness import bootstrap
from opa.harness.service import HarnessService

USER_CLAUDE_MD = """# My Project

- write commit messages in Korean
- no merge without tests

done.
"""


@pytest.fixture
def harness(tmp_path):
    return HarnessService(tmp_path / "state" / "local", tmp_path / "state" / "global")


def test_auto_only_writes_files_that_already_exist(harness, tmp_path):
    """Creating files the user never had is itself "changing the environment"."""
    (tmp_path / "CLAUDE.md").write_text(USER_CLAUDE_MD, encoding="utf-8")
    harness.create("prompt", "run generate", "after a migration, run prisma generate")

    result = bootstrap.run(harness, tmp_path, tmp_path / ".opa")
    assert result.agents == ["claude-code"]
    assert not (tmp_path / "AGENTS.md").exists()


def test_auto_falls_back_to_agents_md_when_nothing_exists(harness, tmp_path):
    harness.create("prompt", "t", "c")
    bootstrap.run(harness, tmp_path, tmp_path / ".opa")
    assert (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()


def test_round_trip_leaves_the_file_byte_identical(harness, tmp_path):
    (tmp_path / "CLAUDE.md").write_text(USER_CLAUDE_MD, encoding="utf-8")
    harness.create("prompt", "run generate", "after a migration, run prisma generate")
    harness.create("skill", "migration check", "check that generate ran")

    bootstrap.run(harness, tmp_path, tmp_path / ".opa")
    assert (tmp_path / ".claude" / "skills" / "migration-check" / "SKILL.md").exists()
    assert (tmp_path / "CLAUDE.md").read_text() != USER_CLAUDE_MD

    bootstrap.run(harness, tmp_path, tmp_path / ".opa", remove=True)
    assert (tmp_path / "CLAUDE.md").read_text() == USER_CLAUDE_MD
    assert not (tmp_path / ".claude" / "skills" / "migration-check").exists()


def test_running_twice_changes_nothing_the_second_time(harness, tmp_path):
    (tmp_path / "CLAUDE.md").write_text(USER_CLAUDE_MD, encoding="utf-8")
    harness.create("prompt", "t", "c")
    first = bootstrap.run(harness, tmp_path, tmp_path / ".opa")
    second = bootstrap.run(harness, tmp_path, tmp_path / ".opa")
    assert first.updated and not second.updated
    assert second.unchanged


def test_explicit_unknown_agent_is_rejected(harness, tmp_path):
    with pytest.raises(ValueError, match="unknown agent"):
        bootstrap.run(harness, tmp_path, tmp_path / ".opa", agent="emacs")


def test_memory_bodies_never_land_in_the_prompt_file(harness, tmp_path):
    """Context is for deciding, not for storage — that holds for the projection too."""
    (tmp_path / "CLAUDE.md").write_text(USER_CLAUDE_MD, encoding="utf-8")
    harness.create("memory", "service ports", "api=8080 " * 300)
    bootstrap.run(harness, tmp_path, tmp_path / ".opa")

    text = (tmp_path / "CLAUDE.md").read_text()
    assert "api=8080 api=8080" not in text
    assert ".opa/memory/service-ports.md" in text
    assert (tmp_path / ".opa" / "memory" / "service-ports.md").exists()


def test_a_symlinked_prompt_file_is_reported_once(harness, tmp_path):
    """`CLAUDE.md -> AGENTS.md` is a common setup. Writing through the link twice
    reported two updated files for one edit."""
    (tmp_path / "AGENTS.md").write_text(USER_CLAUDE_MD, encoding="utf-8")
    (tmp_path / "CLAUDE.md").symlink_to("AGENTS.md")
    harness.create("prompt", "run generate", "after migrations")

    result = bootstrap.run(harness, tmp_path, tmp_path / ".opa")

    assert len(result.updated) + len(result.unchanged) == 1
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert text.count("opa:begin") == 1
    assert (tmp_path / "CLAUDE.md").is_symlink(), "the link itself must survive"


def test_removing_through_a_symlink_restores_the_target(harness, tmp_path):
    (tmp_path / "AGENTS.md").write_text(USER_CLAUDE_MD, encoding="utf-8")
    (tmp_path / "CLAUDE.md").symlink_to("AGENTS.md")
    harness.create("prompt", "t", "c")

    bootstrap.run(harness, tmp_path, tmp_path / ".opa")
    bootstrap.run(harness, tmp_path, tmp_path / ".opa", remove=True)

    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == USER_CLAUDE_MD
    assert (tmp_path / "CLAUDE.md").is_symlink()
