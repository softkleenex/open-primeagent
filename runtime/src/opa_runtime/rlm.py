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
    rlm_child_id: str
    name: str
    adapter: str
    status: str
    turns: int
    tokens: int
    cost_usd: float
    model: str | None
    session_dir: Path
    last_error: str | None = None

    def __repr__(self) -> str:
        return (
            f"<subagent {self.name!r} ({self.adapter}) {self.status} "
            f"turns={self.turns} tokens={self.tokens}>"
        )


async def run(prompt: str, **kwargs: Any) -> RLMSpawnHandle:
    """Create one independent agent session and return as soon as it is admitted.

    name           the child's address, used to re-task it later. **Required**.
    model          passed straight to the host CLI - which is why we build no
                   provider layer of our own.
    adapter        "claude-code" | "codex". Defaults to the configured backend.
    cwd            must stay inside the workspace.
    system_prompt  a standing role spec for the child.
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
        return [
            RLMSubagent(
                rlm_child_id=entry["rlm_child_id"],
                name=entry["name"],
                adapter=entry["adapter"],
                status=entry["status"],
                turns=entry["turns"],
                tokens=entry["tokens"],
                cost_usd=entry["cost_usd"],
                model=entry.get("model"),
                session_dir=Path(entry["session_dir"]),
                last_error=entry.get("last_error"),
            )
            for entry in payload["subagents"]
        ]

    async def delete_subagent(self, target: str | RLMSubagent) -> dict:
        selector = target.name if isinstance(target, RLMSubagent) else str(target).strip()
        payload = await host_request("rlm.delete_subagent", {"target": selector})
        return payload["deleted"]

    async def __call__(self, prompt: str, **kwargs: Any) -> RLMSpawnHandle:
        return await run(prompt, **kwargs)


rlm = _RLM()
