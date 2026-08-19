"""opa_bootstrap — 현재 호스트에 harness projection과 스킬을 설치/갱신.

델리미터 블록 안에서만 쓴다. 블록 밖 사용자 내용은 건드리지 않는다.
`remove=True` 로 완전 원상복구가 가능해야 한다 — 이게 "환경을 안 바꾼다"의 증명이다.
"""

DESCRIPTION = """\
Install or refresh open-primeagent's harness projection for the current host
agent (CLAUDE.md / AGENTS.md block, skills). Writes only inside a delimited
block; content outside it is preserved byte-for-byte. Pass remove=true to
restore the files to their original state.
"""
