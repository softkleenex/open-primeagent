"""Codex 어댑터.

    spawn :  codex exec <PROMPT> --json [-m MODEL]
    resume:  codex exec resume <SESSION_ID> <PROMPT> --json

claude와 달리 세션 id를 우리가 정할 수 없다 — 첫 실행의 JSONL 이벤트에서
파싱해 registry에 저장해야 한다.
"""

from __future__ import annotations

CLI = "codex"


class CodexAdapter:
    name = "codex"

    def available(self) -> bool:
        raise NotImplementedError

    async def spawn(self, spec, session_dir):
        raise NotImplementedError

    async def resume(self, sess, prompt, session_dir):
        raise NotImplementedError

    def parse_event(self, line: str) -> dict | None:
        raise NotImplementedError
