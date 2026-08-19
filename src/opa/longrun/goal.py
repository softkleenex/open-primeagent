"""persistent goal — 끝날 때까지 유지되는 목표. `<session>/goal.json`.

원본 규칙: 완료는 오직 `goal.complete()` 호출로만. 말로 끝났다고 하면 안 된다.
예산이 떨어졌다는 이유로 complete 하지 않는다.
"""

from __future__ import annotations


class Goal:
    async def get(self) -> dict: ...
    async def create(self, objective: str, token_budget: int | None = None) -> dict: ...
    async def complete(self) -> dict: ...
