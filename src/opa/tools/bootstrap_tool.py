"""opa_bootstrap — 현재 호스트에 harness projection과 스킬을 설치/갱신.

델리미터 블록 안에서만 쓴다. 블록 밖 사용자 내용은 건드리지 않는다.
`remove=True` 로 완전 원상복구가 가능해야 한다 — 이게 "환경을 안 바꾼다"의 증명이다.
"""

DESCRIPTION = """\
Project the continual harness (prompt notes, memory index, skills) into the
files this coding agent already reads: CLAUDE.md / AGENTS.md and .claude/skills.

Writes ONLY inside a delimited `<!-- opa:begin -->` block; everything outside it
is preserved byte-for-byte. agent="auto" targets the prompt files that already
exist. Pass remove=true to restore every touched file to its original state.

Call this after changing harness entries so the next session starts with them.
"""
