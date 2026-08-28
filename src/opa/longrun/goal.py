"""Persistent goal - an objective that survives turns. `<session>/goal.json`.

Upstream's rule, kept: only a `goal.complete()` call ends a goal. Saying it is
done does not, and running low on budget is not a reason to complete.

We do not own the host's turn loop, so we cannot re-prompt anyone. What a goal
does here is survive: it stays in `opa_status()` until something explicitly ends
it, so a host agent that lost its context still finds out what it was doing.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

GoalStatus = Literal["active", "completed", "abandoned", "budget_exhausted"]
PENDING: tuple[GoalStatus, ...] = ("active",)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Goal:
    objective: str
    status: GoalStatus = "active"
    token_budget: int | None = None
    tokens_used: int = 0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    completed_at: str | None = None
    note: str = ""

    @property
    def remaining_tokens(self) -> int | None:
        if self.token_budget is None:
            return None
        return max(self.token_budget - self.tokens_used, 0)

    @property
    def exhausted(self) -> bool:
        return self.token_budget is not None and self.tokens_used >= self.token_budget


class GoalStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.goal: Goal | None = None
        self.load()

    def load(self) -> GoalStore:
        self.goal = None
        if not self.path.exists():
            return self
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self  # a corrupt goal file must not block the session
        if isinstance(data, dict) and isinstance(data.get("objective"), str):
            known = {f for f in Goal.__dataclass_fields__}
            self.goal = Goal(**{k: v for k, v in data.items() if k in known})
        return self

    def save(self) -> GoalStore:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.goal is None:
            self.path.unlink(missing_ok=True)
        else:
            self.path.write_text(
                json.dumps(asdict(self.goal), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        return self

    # ---------- API ----------

    def create(self, objective: str, token_budget: int | None = None) -> Goal:
        if not isinstance(objective, str) or not objective.strip():
            raise ValueError("objective must be a non-empty string")
        if self.goal is not None and self.goal.status in PENDING:
            raise ValueError(
                f"a goal is still active: {self.goal.objective!r}. "
                "Complete or abandon it before starting another."
            )
        if token_budget is not None and (not isinstance(token_budget, int) or token_budget <= 0):
            raise ValueError("token_budget must be a positive integer")
        self.goal = Goal(objective=objective.strip(), token_budget=token_budget)
        self.save()
        return self.goal

    def get(self) -> dict[str, Any]:
        if self.goal is None:
            return {"goal": None}
        return {
            "goal": asdict(self.goal),
            "remaining_tokens": self.goal.remaining_tokens,
            "budget_exhausted": self.goal.exhausted,
        }

    def spend(self, tokens: int) -> Goal | None:
        """Charge tokens against the active goal. Called wherever tokens are burned."""
        if self.goal is None or self.goal.status not in PENDING or tokens <= 0:
            return self.goal
        self.goal.tokens_used += int(tokens)
        self.goal.updated_at = _now()
        if self.goal.exhausted:
            self.goal.status = "budget_exhausted"
            self.goal.note = "stopped by token budget; the objective was not completed"
        self.save()
        return self.goal

    def complete(self) -> dict[str, Any]:
        if self.goal is None:
            raise ValueError("there is no goal to complete")
        if self.goal.status == "completed":
            raise ValueError("this goal is already completed")
        self.goal.status = "completed"
        self.goal.completed_at = _now()
        self.goal.updated_at = self.goal.completed_at
        self.save()
        return {
            "goal": asdict(self.goal),
            "budget_report": {
                "token_budget": self.goal.token_budget,
                "tokens_used": self.goal.tokens_used,
                "remaining_tokens": self.goal.remaining_tokens,
            },
        }

    def abandon(self, note: str = "") -> dict[str, Any]:
        """Stop pursuing a goal without claiming it was achieved."""
        if self.goal is None:
            raise ValueError("there is no goal to abandon")
        self.goal.status = "abandoned"
        self.goal.note = note
        self.goal.updated_at = _now()
        self.save()
        return {"goal": asdict(self.goal)}
