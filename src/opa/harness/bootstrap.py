"""opa_bootstrap — harness를 호스트가 읽는 파일로 설치/갱신/제거한다.

호스트마다 읽는 파일이 다르다:

    claude-code : CLAUDE.md   + .claude/skills/
    codex       : AGENTS.md
    opencode    : AGENTS.md

기본 동작(`agent="auto"`)은 **이미 있는 파일에만** 쓰는 것이다. 없는 파일을
새로 만들어대면 그것 자체가 "환경을 바꾸는" 짓이다. 하나도 없으면 가장
범용적인 `AGENTS.md` 하나만 만든다.
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
    """이미 존재하는 프롬프트 파일로 호스트를 추정한다."""
    found = [
        name
        for name, spec in HOSTS.items()
        if spec["prompt_file"] and (workspace / str(spec["prompt_file"])).exists()
    ]
    # AGENTS.md 하나로 codex/opencode가 겹치므로 중복 타깃을 줄인다
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
        agents = detect(workspace) or ["codex"]  # 없으면 AGENTS.md 하나
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
