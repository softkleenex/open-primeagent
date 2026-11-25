"""Projection - render harness state into the files the host already reads.

We do not own the system prompt. That is this project's unique problem, and the
answer is to write into files the host reads anyway.

    prompt   -> a delimiter block inside CLAUDE.md / AGENTS.md
    skill    (K) → .claude/skills/<n>/SKILL.md
    memory   -> .opa/memory/*.md; only an index goes into the prompt block
    subagent -> registry default spec (--append-system-prompt at spawn)

**Invariant: we write only inside the delimiters.**
Changing even one character of the user's own prose breaks the promise that we
do not change their environment. `tests/test_projection.py` enforces it.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..fsutil import atomic_write
from .state import HarnessEntry

BEGIN = "<!-- opa:begin — generated. Nothing outside this block is touched. -->"
# Same marker, recording that the user's file had no final newline before we
# appended. Without it, apply-then-remove could not give back the exact bytes.
BEGIN_NO_EOL = (
    "<!-- opa:begin (no final newline) — generated. Nothing outside this block is touched. -->"
)
END = "<!-- opa:end -->"

# A marker counts only when it is a whole line. The old pattern matched
# `<!-- opa:begin` anywhere, so a user who quoted the marker in their own prose -
# our README shows it - had everything from that mention to our END erased on
# the next apply. Matching loosely *inside* the line still finds a block written
# with older wording.
_BEGIN_LINE = re.compile(r"[ \t]*<!--\s*opa:begin\b.*-->[ \t]*")
_END_LINE = re.compile(r"[ \t]*<!--\s*opa:end\s*-->[ \t]*")


class ProjectionConflict(ValueError):
    """The file's markers are ambiguous, so any edit could hit the user's text."""


MEMORY_DIR_NAME = "memory"

# This block is read on every request, so it is budgeted like one. Entries are
# routing hints - enough to know a rule exists and go read it - not the rules
# themselves. Upstream applies the same discipline for the same reason.
MAX_PER_KIND = 6
SUMMARY_CHARS = 180
# Rules get more room than the other summaries. This file is also what Codex,
# opencode and a teammate without open-primeagent read, and for them a rule cut
# off mid-sentence has no `harness.overview()` to finish it. Measured: a rule
# recorded in a real run was cut right after the script name it needed.
RULE_CHARS = 400


def _inside(directory: Path, name: str) -> Path:
    """Resolve `name` under `directory`, refusing to escape it.

    Entry ids are validated on creation, but projection is the layer that
    actually writes, so it checks again rather than trusting its input.
    """
    root = directory.resolve()
    candidate = (root / name).resolve()
    if root not in candidate.parents:
        # `candidate == root` used to pass. An id of "" or "." resolves to the
        # directory itself, so an entry loaded from a hand-edited or
        # upstream-written state file - ids are validated on creation, never on
        # load - made us write `.opa-managed` and `SKILL.md` into the user's
        # skills root. Our own uninstall only looks at child directories, so
        # that litter was permanent, and the stray ownership marker claimed the
        # whole directory.
        #
        # A caller asking for a name under a directory always means a child.
        raise ValueError(f"refusing to write {name!r} outside {root}")
    return candidate


def _section(lines: list[str], heading: str, entries: list, render_one) -> None:
    if not entries:
        return
    shown = entries[:MAX_PER_KIND]
    lines.append(f"### {heading} ({len(entries)})")
    lines.append("")
    lines += [render_one(entry) for entry in shown]
    if len(entries) > len(shown):
        lines.append(f"- … {len(entries) - len(shown)} more — `await harness.overview()`")
    lines.append("")


def render(entries: list[HarnessEntry], *, memory_dir: Path | None = None) -> str:
    """Render the block body: an index of what exists, not the content itself."""
    prompts = [e for e in entries if e.kind == "prompt"]
    memories = [e for e in entries if e.kind == "memory"]
    skills = [e for e in entries if e.kind == "skill"]

    lines: list[str] = ["## open-primeagent", ""]
    if not (prompts or memories or skills):
        lines.append("_(harness is empty)_")
        return "\n".join(lines)

    lines.append(
        "What agents have learned about this project, recorded so the next one "
        "does not rediscover it. The rules are written out to be followed by any "
        "agent that reads this file, with or without open-primeagent. Kept short "
        "because it is read on every request; with open-primeagent attached, "
        "`await harness.overview()` shows every entry in full."
    )
    lines.append("")

    _section(
        lines,
        "Rules for this project",
        prompts,
        lambda e: f"- **{_one_line(e.title, SUMMARY_CHARS)}** — {_one_line(e.content, RULE_CHARS)}",
    )
    _section(
        lines,
        "Memory index",
        memories,
        lambda e: (
            f"- {_one_line(e.title, SUMMARY_CHARS)} → "
            + (f"`.opa/{MEMORY_DIR_NAME}/{e.id}.md`" if memory_dir else f"`{e.id}`")
        ),
    )
    _section(
        lines, "Skills", skills, lambda e: f"- `{e.id}` — {_one_line(e.content, SUMMARY_CHARS)}"
    )

    return "\n".join(lines).rstrip() + "\n"


def _one_line(text: str, limit: int = 160) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _eol(text: str) -> str:
    """The file's own line ending. We write in it rather than normalising."""
    return "\r\n" if "\r\n" in text else "\n"


def _is_marker(line: str) -> bool:
    bare = line.rstrip("\r\n")
    return bool(_BEGIN_LINE.fullmatch(bare) or _END_LINE.fullmatch(bare))


def _locate(text: str) -> tuple[int, int, bool] | None:
    """Byte span of our block (whole lines, trailing EOL included), or None.

    Also returns whether the block records a missing final newline. Anything
    other than exactly one BEGIN line followed by exactly one END line is
    refused: a guess about which marker is ours is a guess about which of the
    user's lines to delete.
    """
    lines = text.splitlines(keepends=True)
    begins = [i for i, ln in enumerate(lines) if _BEGIN_LINE.fullmatch(ln.rstrip("\r\n"))]
    ends = [i for i, ln in enumerate(lines) if _END_LINE.fullmatch(ln.rstrip("\r\n"))]
    if not begins and not ends:
        return None
    if len(begins) != 1 or len(ends) != 1 or ends[0] < begins[0]:
        raise ProjectionConflict(
            f"found {len(begins)} opa:begin and {len(ends)} opa:end marker line(s); "
            "refusing to edit a file where our block is ambiguous. Leave exactly "
            "one block, or delete the markers by hand."
        )
    start = sum(len(ln) for ln in lines[: begins[0]])
    stop = sum(len(ln) for ln in lines[: ends[0] + 1])
    no_eol = "no final newline" in lines[begins[0]]
    return start, stop, no_eol


def block(body: str, *, eol: str = "\n", no_eol: bool = False) -> str:
    lines = body.rstrip().splitlines()
    if any(_is_marker(ln) for ln in lines):
        # A marker line inside the body would end the block early on the next
        # read, and everything after it would be stranded in the user's file.
        raise ProjectionConflict("the projected body contains an opa marker line")
    head = BEGIN_NO_EOL if no_eol else BEGIN
    return eol.join([head, *lines, END]) + eol


def _read(target: Path) -> str:
    # newline="": see the file's real line endings instead of translated ones.
    with target.open(encoding="utf-8", newline="") as fh:
        return fh.read()


def apply(target: Path, body: str) -> bool:
    """Replace only the delimiter block; append one if the file has none.

    Everything outside the block is preserved byte for byte, and `remove`
    restores the original exactly. Returns True if the file changed.
    """
    existing = _read(target) if target.exists() else ""
    eol = _eol(existing)
    found = _locate(existing)

    if found:
        start, stop, no_eol = found
        updated = existing[:start] + block(body, eol=eol, no_eol=no_eol) + existing[stop:]
    elif existing:
        # One blank line between the user's text and ours. A file without a
        # final newline needs one more, and the marker remembers that we added it.
        no_eol = not existing.endswith(("\n", "\r"))
        sep = eol + eol if no_eol else eol
        updated = existing + sep + block(body, eol=eol, no_eol=no_eol)
    else:
        updated = block(body, eol=eol)

    if updated == existing:
        return False
    atomic_write(target, updated)
    return True


def remove(target: Path) -> bool:
    """Remove the block and restore the file. The uninstall path must exist."""
    if not target.exists():
        return False
    existing = _read(target)
    found = _locate(existing)
    if not found:
        return False
    start, stop, no_eol = found
    before, after = existing[:start], existing[stop:]
    if not after.strip():
        # The block is still where `apply` appended it: also take back the
        # separator we added, and nothing else.
        eol = _eol(existing)
        sep = eol + eol if no_eol else eol
        before = before.removesuffix(sep)
        after = ""
    updated = before + after

    if not updated:
        # The file held nothing but our block, so leaving no trace is the
        # tidiest outcome - but only when the name we were given is the file
        # itself. `read_text` follows a symlink and the removal below does not,
        # so uninstalling through `CLAUDE.md -> AGENTS.md` used to take out the
        # user's link *and* leave our block sitting in the file it pointed at:
        # wrong on both counts, from the one path whose whole job is to undo us.
        #
        # Through a link we empty the target and keep both. An empty file is not
        # a loss; someone's symlink is.
        if target.is_symlink():
            atomic_write(target, "")
            return True
        target.unlink()
        return True
    atomic_write(target, updated)
    return True


def write_memories(memory_dir: Path, entries: list[HarnessEntry]) -> list[Path]:
    """Memory bodies go to their own files; only an index enters the prompt block."""
    memory_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    wanted = {e.id for e in entries if e.kind == "memory"}
    for entry in entries:
        if entry.kind != "memory":
            continue
        path = _inside(memory_dir, f"{entry.id}.md")
        atomic_write(path, f"# {entry.title}\n\n{entry.content.rstrip()}\n")
        written.append(path)
    for stale in memory_dir.glob("*.md"):
        if stale.stem not in wanted:
            stale.unlink()
    return written


def _prune_managed(directory: Path) -> None:
    """Take out a whole directory we own, in one call.

    Deleting entry by entry looked safer and was not. Iteration order put
    `.opa-managed` first, so a nested directory - anything the host or the user
    drops beside our SKILL.md - raised partway through and left the worst
    possible state: the ownership marker gone, the stale SKILL.md still there.
    We could then never recognise the directory as ours again, so it was never
    cleaned up, while the host went on loading the skill it still contained.

    The marker is checked by the caller; `shutil.rmtree` removes bottom-up, so
    the marker is among the last things to go and a failure leaves ownership
    legible.
    """
    shutil.rmtree(directory)


def write_skills(skills_dir: Path, entries: list[HarnessEntry]) -> list[Path]:
    """Drop skills as SKILL.md where the host already looks for them.

    Only directories we created (marked `.opa-managed`) are ever pruned. Deleting
    a skill the user wrote themselves would break the promise.
    """
    written: list[Path] = []
    wanted: set[str] = set()
    for entry in entries:
        if entry.kind != "skill":
            continue
        wanted.add(entry.id)
        directory = _inside(skills_dir, entry.id)
        directory.mkdir(parents=True, exist_ok=True)
        # The ownership marker is written before any content, so a directory
        # we created is always recognisable as ours to prune - even if we die
        # immediately after making it.
        atomic_write(directory / ".opa-managed", entry.id)
        atomic_write(
            directory / "SKILL.md",
            f"---\nname: {entry.id}\ndescription: {_one_line(entry.title, 200)}\n---\n\n"
            f"{entry.content.rstrip()}\n",
        )
        written.append(directory / "SKILL.md")

    if skills_dir.exists():
        for directory in skills_dir.iterdir():
            managed = directory.is_dir() and (directory / ".opa-managed").exists()
            if managed and directory.name not in wanted:
                _prune_managed(directory)
    return written


def remove_skills(skills_dir: Path) -> int:
    """Remove only the skill directories we created."""
    if not skills_dir.exists():
        return 0
    removed = 0
    for directory in list(skills_dir.iterdir()):
        if directory.is_dir() and (directory / ".opa-managed").exists():
            _prune_managed(directory)
            removed += 1
    return removed
