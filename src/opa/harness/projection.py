"""projection — harness 상태를 호스트가 이미 읽는 파일로 투영한다.

우리는 시스템 프롬프트를 소유하지 않는다. 이게 이 프로젝트 고유의 문제이고,
해법은 호스트가 어차피 읽는 파일에 쓰는 것이다.

    prompt   (ρ) → CLAUDE.md / AGENTS.md 의 델리미터 블록
    skill    (K) → .claude/skills/<n>/SKILL.md
    memory   (M) → .opa/memory/*.md, 프롬프트 블록에는 인덱스만
    subagent (G) → registry default spec (spawn 시 --append-system-prompt)

**불변식: 쓰기는 오직 델리미터 안에서만.**
사용자가 쓴 내용을 한 글자라도 바꾸면 "환경을 안 바꾼다"는 약속이 깨진다.
`tests/test_projection.py` 가 이걸 강제한다.
"""

from __future__ import annotations

import re
from pathlib import Path

from .state import HarnessEntry

BEGIN = "<!-- opa:begin — 자동 생성. 이 블록 밖은 건드리지 않음. -->"
END = "<!-- opa:end -->"

# 마커 앞뒤 공백과 안내문이 바뀌어도 기존 블록을 찾아낸다.
_BLOCK = re.compile(
    r"[ \t]*<!--\s*opa:begin.*?-->.*?<!--\s*opa:end\s*-->[ \t]*\n?",
    re.DOTALL,
)

MEMORY_DIR_NAME = "memory"


def render(entries: list[HarnessEntry], *, memory_dir: Path | None = None) -> str:
    """prompt 엔트리 + memory 인덱스 + skill 목록을 블록 본문으로 렌더."""
    prompts = [e for e in entries if e.kind == "prompt"]
    memories = [e for e in entries if e.kind == "memory"]
    skills = [e for e in entries if e.kind == "skill"]

    lines: list[str] = ["## open-primeagent", ""]
    if not (prompts or memories or skills):
        lines.append("_(harness is empty)_")
        return "\n".join(lines)

    if prompts:
        lines.append("### 이 프로젝트에서 지킬 것")
        lines.append("")
        for entry in prompts:
            lines.append(f"- **{entry.title}** — {_one_line(entry.content)}")
        lines.append("")

    if memories:
        # 본문이 아니라 **인덱스만** 넣는다. 컨텍스트를 창고로 쓰지 않는다는
        # 이 프로젝트의 전제가 투영에도 그대로 적용된다.
        lines.append("### 메모리 인덱스")
        lines.append("")
        for entry in memories:
            location = f"`.opa/{MEMORY_DIR_NAME}/{entry.id}.md`" if memory_dir else f"`{entry.id}`"
            lines.append(f"- {entry.title} → {location}")
        lines.append("")

    if skills:
        lines.append("### 스킬")
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
    """target의 델리미터 블록만 교체한다. 블록이 없으면 파일 끝에 추가.

    블록 밖은 바이트 단위로 보존한다. 변경이 있었으면 True.
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
    """블록을 제거해 원상복구한다. 언인스톨 경로 — 반드시 있어야 한다."""
    if not target.exists():
        return False
    existing = target.read_text(encoding="utf-8")
    if not _BLOCK.search(existing):
        return False
    updated = _BLOCK.sub("", existing, count=1)
    # 블록만 있던 파일이면 흔적을 남기지 않는다.
    if not updated.strip():
        target.unlink()
        return True
    target.write_text(updated.rstrip("\n") + "\n", encoding="utf-8")
    return True


def write_memories(memory_dir: Path, entries: list[HarnessEntry]) -> list[Path]:
    """memory 본문은 별도 파일로. 프롬프트 블록에는 인덱스만 들어간다."""
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
    """skill 은 호스트가 이미 읽는 위치에 SKILL.md 로 떨어뜨린다.

    우리가 만든 디렉터리만 지운다 (`.opa-managed` 표식이 있는 것). 사용자가 직접
    만든 스킬을 지우면 "환경을 안 바꾼다"는 약속이 깨진다.
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
    """우리가 만든 스킬 디렉터리만 제거한다."""
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
