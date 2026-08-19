"""autonomous — gate 통과까지 스스로 다음 턴을 실행한다.

정지 조건: max turns / token budget / wall-clock timeout.
quality gate 실패 시 **그 출력을 다음 턴의 입력으로 되먹인다** — 이게
단순 cron 기반 AI 스크립트와의 차이다.

⚠️ 이 모드는 감시 없이 파일을 고치고 명령을 실행한다.
   devcontainer/VM 밖에서 쓰지 말 것 (docs/security.md).
"""

from __future__ import annotations


class AutonomousRun:
    async def start(self, *, max_turns: int, token_budget: int | None,
                    wall_clock_seconds: int | None, gate: str | None) -> dict: ...
    async def stop(self) -> dict: ...
