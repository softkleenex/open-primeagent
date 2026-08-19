"""Heartbeat - drop a reminder into the mailbox at an interval.

User-created (`/heartbeat`) and agent-created (`rlm_heartbeat`) stay separate,
as upstream keeps them.
"""

from __future__ import annotations


class Heartbeat:
    async def create(self, interval_seconds: int, message: str, *, source: str = "user") -> dict: ...
    async def list(self) -> list[dict]: ...
    async def delete(self, id: str) -> dict: ...
