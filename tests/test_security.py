"""Security invariants that are reachable from model-generated code.

Everything here is callable from inside `opa_python`, which means it is
callable by a prompt-injected instruction. These are not theoretical.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from opa.harness import projection
from opa.harness.service import HarnessService
from opa.harness.state import validate_id


@pytest.fixture
def harness(tmp_path):
    return HarnessService(tmp_path / "local", tmp_path / "global")


@pytest.mark.parametrize(
    "unsafe", ["../../CLAUDE", "../escape", "a/b", "..", "/etc/passwd", "a\\b", "."]
)
def test_unsafe_entry_ids_are_rejected(harness, unsafe):
    """Entry ids become file names during projection, so `../../CLAUDE` would
    write outside the target directory."""
    with pytest.raises(ValueError, match="unsafe harness id"):
        harness.create("memory", "innocent looking", "payload", id=unsafe)


def test_safe_ids_still_work(harness):
    assert harness.create("memory", "ports", "api=8080", id="ports").id == "ports"
    assert validate_id("some-note") == "some-note"


def test_generated_ids_are_always_safe(harness):
    """Titles are attacker-controlled too, but ids derived from them are slugged."""
    entry = harness.create("memory", "../../escape attempt", "x")
    assert "/" not in entry.id
    assert ".." not in entry.id


@dataclass
class ForgedEntry:
    kind: str = "memory"
    id: str = "../escape"
    title: str = "t"
    content: str = "c"


def test_projection_refuses_to_write_outside_its_directory(tmp_path):
    """Defence in depth: projection is where the write happens, so it checks
    again instead of trusting that ids were validated upstream."""
    with pytest.raises(ValueError, match="refusing to write"):
        projection.write_memories(tmp_path / "memory", [ForgedEntry()])


def test_projection_refuses_to_create_skill_dirs_outside(tmp_path):
    with pytest.raises(ValueError, match="refusing to write"):
        projection.write_skills(tmp_path / "skills", [ForgedEntry(kind="skill")])


def test_mailbox_names_cannot_escape(tmp_path):
    from opa.rlm.message import Mailbox

    box = Mailbox(tmp_path / "mailbox")
    path = box.path("../../escape")
    assert (tmp_path / "mailbox").resolve() in path.resolve().parents


async def test_child_cwd_cannot_escape_the_workspace(config):
    from opa.rlm.spawn import RLMService

    service = RLMService(config, config.root / "children", config.root / "mailbox")
    for outside in ["/etc", "../..", str(config.workspace.parent)]:
        with pytest.raises(ValueError, match="outside the workspace"):
            service._resolve_cwd(outside)
