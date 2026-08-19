"""Claude Code 어댑터 (기본값).

    spawn :  claude -p <PROMPT> --session-id <UUID> --output-format stream-json
             [--model M] [--append-system-prompt SPEC] [--permission-mode MODE]
    resume:  claude -p <PROMPT> --resume <UUID>  --output-format stream-json

세션 UUID를 **우리가 발급**할 수 있는 게 크다 — registry id와 native session id를
1:1로 묶어둘 수 있어 복구 로직이 단순해진다.

보안: --dangerously-skip-permissions 는 Config.allow_dangerous_child 일 때만.
"""

from __future__ import annotations

CLI = "claude"


class ClaudeCodeAdapter:
    name = "claude-code"

    def available(self) -> bool:
        raise NotImplementedError

    async def spawn(self, spec, session_dir):
        raise NotImplementedError

    async def resume(self, sess, prompt, session_dir):
        raise NotImplementedError

    def parse_event(self, line: str) -> dict | None:
        raise NotImplementedError
