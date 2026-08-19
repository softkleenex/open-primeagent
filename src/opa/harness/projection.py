"""projection — harness 상태를 호스트가 이미 읽는 파일로 투영한다.

우리는 시스템 프롬프트를 소유하지 않는다. 이게 이 프로젝트 고유의 문제이고,
해법은 호스트가 어차피 읽는 파일에 쓰는 것이다.

    prompt   (ρ) → CLAUDE.md / AGENTS.md 의 델리미터 블록
    skill    (K) → .claude/skills/<n>/SKILL.md  (+ python 패키지는 커널에 설치)
    memory   (M) → .opa/memory/*.md, 프롬프트 블록에는 인덱스만
    subagent (G) → registry default spec (spawn 시 --append-system-prompt)

**불변식: 쓰기는 오직 델리미터 안에서만.**
사용자가 직접 쓴 내용을 한 글자라도 바꾸면 "환경을 안 바꾼다"는 약속이 깨진다.
tests/test_projection.py 가 이걸 강제한다.
"""

from __future__ import annotations

from pathlib import Path

BEGIN = "<!-- opa:begin — 자동 생성. 이 블록 밖은 건드리지 않음. -->"
END = "<!-- opa:end -->"


def render(entries: list) -> str:
    """prompt 엔트리 + memory 인덱스를 블록 본문으로 렌더."""
    raise NotImplementedError


def apply(target: Path, body: str) -> bool:
    """target의 델리미터 블록만 교체한다. 블록이 없으면 파일 끝에 추가.
    블록 밖은 바이트 단위로 보존한다. 변경이 있었으면 True."""
    raise NotImplementedError


def remove(target: Path) -> bool:
    """블록을 제거해 원상복구한다. 언인스톨 경로 — 반드시 있어야 한다."""
    raise NotImplementedError
