"""opa_bootstrap - install, refresh or remove the harness projection.

Different hosts read different files:

    claude-code : CLAUDE.md   + .claude/skills/
    codex       : AGENTS.md
    opencode    : AGENTS.md

The default (`agent="auto"`) writes **only to files that already exist**.
Creating files the user never had would itself be changing their environment.
If none exist we create just one - the most portable, `AGENTS.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import projection
from .service import HarnessService

HOSTS: dict[str, dict[str, str | None]] = {
    "claude-code": {"prompt_file": "CLAUDE.md", "skills_dir": ".claude/skills"},
    "codex": {"prompt_file": "AGENTS.md", "skills_dir": None},
    "opencode": {"prompt_file": "AGENTS.md", "skills_dir": None},
}
FALLBACK_PROMPT_FILE = "AGENTS.md"


@dataclass
class BootstrapResult:
    agents: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    memories: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "agents": self.agents,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "memories": self.memories,
            "skills": self.skills,
            "removed": self.removed,
        }


def detect(workspace: Path) -> list[str]:
    """Infer the host from which prompt files already exist."""
    found = [
        name
        for name, spec in HOSTS.items()
        if spec["prompt_file"] and (workspace / str(spec["prompt_file"])).exists()
    ]
    # codex and opencode share AGENTS.md, so collapse duplicate targets
    seen: set[str] = set()
    unique: list[str] = []
    for name in found:
        target = str(HOSTS[name]["prompt_file"])
        if target not in seen:
            seen.add(target)
            unique.append(name)
    return unique


def run(
    harness: HarnessService,
    workspace: Path,
    opa_root: Path,
    *,
    agent: str = "auto",
    remove: bool = False,
) -> BootstrapResult:
    result = BootstrapResult()
    memory_dir = opa_root / projection.MEMORY_DIR_NAME

    if agent == "auto":
        agents = detect(workspace) or ["codex"]  # nothing found -> AGENTS.md only
    else:
        if agent not in HOSTS:
            raise ValueError(f"unknown agent {agent!r}. one of: {', '.join(sorted(HOSTS))}, auto")
        agents = [agent]
    result.agents = agents

    if remove:
        for name in agents:
            spec = HOSTS[name]
            target = workspace / str(spec["prompt_file"])
            if projection.remove(target):
                result.removed.append(str(target))
            if spec["skills_dir"]:
                count = projection.remove_skills(workspace / str(spec["skills_dir"]))
                if count:
                    result.removed.append(f"{spec['skills_dir']} ({count} skills)")
        if memory_dir.exists():
            for stale in memory_dir.glob("*.md"):
                stale.unlink()
            result.removed.append(str(memory_dir))
        return result

    entries = harness.list()
    body = projection.render(entries, memory_dir=memory_dir)
    result.memories = [str(p) for p in projection.write_memories(memory_dir, entries)]

    for name in agents:
        spec = HOSTS[name]
        target = workspace / str(spec["prompt_file"] or FALLBACK_PROMPT_FILE)
        (result.updated if projection.apply(target, body) else result.unchanged).append(str(target))
        if spec["skills_dir"]:
            written = projection.write_skills(workspace / str(spec["skills_dir"]), entries)
            result.skills += [str(p) for p in written]
    return result
