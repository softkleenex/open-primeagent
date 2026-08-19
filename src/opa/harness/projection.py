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
from pathlib import Path

from .state import HarnessEntry

BEGIN = "<!-- opa:begin — generated. Nothing outside this block is touched. -->"
END = "<!-- opa:end -->"

# Find an existing block even if the surrounding whitespace or wording changed.
_BLOCK = re.compile(
    r"[ \t]*<!--\s*opa:begin.*?-->.*?<!--\s*opa:end\s*-->[ \t]*\n?",
    re.DOTALL,
)

MEMORY_DIR_NAME = "memory"


def render(entries: list[HarnessEntry], *, memory_dir: Path | None = None) -> str:
    """Render prompt entries, the memory index and the skill list as block body."""
    prompts = [e for e in entries if e.kind == "prompt"]
    memories = [e for e in entries if e.kind == "memory"]
    skills = [e for e in entries if e.kind == "skill"]

    lines: list[str] = ["## open-primeagent", ""]
    if not (prompts or memories or skills):
        lines.append("_(harness is empty)_")
        return "\n".join(lines)

    if prompts:
        lines.append("### Rules for this project")
        lines.append("")
        for entry in prompts:
            lines.append(f"- **{entry.title}** — {_one_line(entry.content)}")
        lines.append("")

    if memories:
        # Only the **index**, never the bodies. "Context is for deciding, not for
        # storage" applies to the projection too.
        lines.append("### Memory index")
        lines.append("")
        for entry in memories:
            location = f"`.opa/{MEMORY_DIR_NAME}/{entry.id}.md`" if memory_dir else f"`{entry.id}`"
            lines.append(f"- {entry.title} → {location}")
        lines.append("")

    if skills:
        lines.append("### Skills")
        lines.append("")
        for entry in skills:
            lines.append(f"- `{entry.id}` — {_one_line(entry.content)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _one_line(text: str, limit: int = 160) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def block(body: str) -> str:
    return f"{BEGIN}\n{body.rstrip()}\n{END}\n"


def apply(target: Path, body: str) -> bool:
    """Replace only the delimiter block; append one if the file has none.

    Everything outside the block is preserved byte for byte. Returns True if the
    file changed.
    """
    new_block = block(body)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""

    if _BLOCK.search(existing):
        updated = _BLOCK.sub(lambda _: new_block, existing, count=1)
    elif existing.strip():
        updated = existing.rstrip("\n") + "\n\n" + new_block
    else:
        updated = new_block

    if updated == existing:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(updated, encoding="utf-8")
    return True


def remove(target: Path) -> bool:
    """Remove the block and restore the file. The uninstall path must exist."""
    if not target.exists():
        return False
    existing = target.read_text(encoding="utf-8")
    if not _BLOCK.search(existing):
        return False
    updated = _BLOCK.sub("", existing, count=1)
    # If the file held nothing but our block, leave no trace behind.
    if not updated.strip():
        target.unlink()
        return True
    target.write_text(updated.rstrip("\n") + "\n", encoding="utf-8")
    return True


def write_memories(memory_dir: Path, entries: list[HarnessEntry]) -> list[Path]:
    """Memory bodies go to their own files; only an index enters the prompt block."""
    memory_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    wanted = {e.id for e in entries if e.kind == "memory"}
    for entry in entries:
        if entry.kind != "memory":
            continue
        path = memory_dir / f"{entry.id}.md"
        path.write_text(f"# {entry.title}\n\n{entry.content.rstrip()}\n", encoding="utf-8")
        written.append(path)
    for stale in memory_dir.glob("*.md"):
        if stale.stem not in wanted:
            stale.unlink()
    return written


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
        directory = skills_dir / entry.id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".opa-managed").write_text(entry.id, encoding="utf-8")
        (directory / "SKILL.md").write_text(
            f"---\nname: {entry.id}\ndescription: {_one_line(entry.title, 200)}\n---\n\n"
            f"{entry.content.rstrip()}\n",
            encoding="utf-8",
        )
        written.append(directory / "SKILL.md")

    if skills_dir.exists():
        for directory in skills_dir.iterdir():
            managed = directory.is_dir() and (directory / ".opa-managed").exists()
            if managed and directory.name not in wanted:
                for child in directory.iterdir():
                    child.unlink()
                directory.rmdir()
    return written


def remove_skills(skills_dir: Path) -> int:
    """Remove only the skill directories we created."""
    if not skills_dir.exists():
        return 0
    removed = 0
    for directory in list(skills_dir.iterdir()):
        if directory.is_dir() and (directory / ".opa-managed").exists():
            for child in directory.iterdir():
                child.unlink()
            directory.rmdir()
            removed += 1
    return removed
