"""`rlm` - the API surface visible from the kernel, shaped like upstream's.

    api = await rlm("audit the API layer", name="api-reviewer")
    children = await rlm.list_subagents()
    await rlm.delete_subagent("api-reviewer")

`rlm(...)` does not wait for a result. It returns a handle and the child keeps
running; collect results with `await agent_message.inbox()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import host_request


@dataclass(frozen=True)
class RLMSpawnHandle:
    rlm_child_id: str
    name: str
    adapter: str
    session_dir: Path
    model: str
    status: str

    def __repr__(self) -> str:
        return f"<rlm child {self.name!r} ({self.adapter}) {self.status}>"


@dataclass(frozen=True)
class RLMSubagent:
    """A retained child.

    `rlm_child_id`, `session_name`, `session_id`, `active_session_id`,
    `session_dir` and `status` are upstream's field names, so code written
    against prime-agent's `rlm` reads this unchanged. `name` and the counters
    below are ours.

    `session_id` is the host CLI's own session identifier; `active_session_id`
    is that same id only while a turn is in flight, and None when the child is
    idle - which is how you tell "this child has a session to resume" from
    "this child is busy right now".
    """

    rlm_child_id: str
    name: str
    adapter: str
    status: str
    turns: int
    tokens: int
    cost_usd: float
    model: str | None
    session_dir: Path
    session_name: str = ""
    session_id: str | None = None
    active_session_id: str | None = None
    last_error: str | None = None

    def __repr__(self) -> str:
        return (
            f"<subagent {self.name!r} ({self.adapter}) {self.status} "
            f"turns={self.turns} tokens={self.tokens}>"
        )


def _subagent(entry: dict[str, Any]) -> RLMSubagent:
    """Parse one child record.

    Only upstream's contract fields are required. Everything else is ours and
    defaults, so a payload in exactly the shape upstream produces parses here
    too - it used to raise `KeyError: 'name'`, which made the compatibility
    one-directional while the README claimed a shared protocol.
    """
    name = entry.get("name") or entry.get("session_name") or ""
    return RLMSubagent(
        rlm_child_id=entry["rlm_child_id"],
        name=name,
        adapter=entry.get("adapter", ""),
        status=entry["status"],
        turns=int(entry.get("turns") or 0),
        tokens=int(entry.get("tokens") or 0),
        cost_usd=float(entry.get("cost_usd") or 0.0),
        model=entry.get("model"),
        session_dir=Path(entry["session_dir"]),
        session_name=entry.get("session_name") or name,
        session_id=entry.get("session_id"),
        active_session_id=entry.get("active_session_id"),
        last_error=entry.get("last_error"),
    )


async def run(prompt: str, **kwargs: Any) -> RLMSpawnHandle:
    """Create one independent agent session and return as soon as it is admitted.

    name           the child's address, used to re-task it later. **Required**.
    model          passed straight to the host CLI - which is why we build no
                   provider layer of our own.
    adapter        "claude-code" | "codex". Defaults to the configured backend.
    cwd            must stay inside the workspace.
    system_prompt  a standing role spec for the child.
    can_message_parent
                   attach the one-tool `opa-child` server so the child can send
                   progress notes mid-run instead of only when it finishes.
    """
    if not isinstance(prompt, str):
        raise TypeError(f"prompt must be str, got {type(prompt).__name__}")
    payload = await host_request("rlm.run", {"prompt": prompt, "kwargs": kwargs})
    return RLMSpawnHandle(
        rlm_child_id=payload["rlm_child_id"],
        name=payload["name"],
        adapter=payload["adapter"],
        session_dir=Path(payload["session_dir"]),
        model=payload["model"],
        status=payload["status"],
    )


class _RLM:
    async def run(self, prompt: str, **kwargs: Any) -> RLMSpawnHandle:
        return await run(prompt, **kwargs)

    async def list_subagents(self) -> list[RLMSubagent]:
        """The same children must come back after a kernel restart or a compaction."""
        payload = await host_request("rlm.list_subagents")
        return [_subagent(entry) for entry in payload["subagents"]]

    async def delete_subagent(self, target: str | RLMSubagent) -> RLMSubagent:
        """Drop one child. Returns the record as it was when it went away."""
        # Address by id, not name: names can be reused, ids cannot.
        selector = (
            target.rlm_child_id if isinstance(target, RLMSubagent) else str(target).strip()
        )
        payload = await host_request("rlm.delete_subagent", {"target": selector})
        return _subagent(payload["subagent"])

    async def __call__(self, prompt: str, **kwargs: Any) -> RLMSpawnHandle:
        return await run(prompt, **kwargs)


rlm = _RLM()
