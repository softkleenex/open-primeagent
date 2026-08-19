"""heartbeat — 일정 간격으로 리마인더를 메일박스에 넣는다.

사용자용(`/heartbeat`)과 에이전트 자율 생성(`rlm_heartbeat`)을 분리한다 (원본과 동일).
"""

from __future__ import annotations


class Heartbeat:
    async def create(self, interval_seconds: int, message: str, *, source: str = "user") -> dict: ...
    async def list(self) -> list[dict]: ...
    async def delete(self, id: str) -> dict: ...
