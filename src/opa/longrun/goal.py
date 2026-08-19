"""Persistent goal - an objective that survives turns. `<session>/goal.json`.

Upstream's rule: only a `goal.complete()` call ends it. Saying it is done does
not. Running low on budget is not a reason to complete.
"""

from __future__ import annotations


class Goal:
    async def get(self) -> dict: ...
    async def create(self, objective: str, token_budget: int | None = None) -> dict: ...
    async def complete(self) -> dict: ...
