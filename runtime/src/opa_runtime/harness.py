"""`harness` - the Continual Harness API visible from the kernel.

    H = (ρ prompts, G subagents, K skills, M memory)

"Self-improving" means **this state** improves, not the model's weights.

    await harness.overview()
    await harness.create("prompt", "regenerate after a migration",
                         "run `pnpm prisma generate` after touching a migration")
    await harness.evidence()                    # grounds for deciding what to change
    await harness.apply([...], trigger="...")   # apply the minimal CRUD delta
    await harness.rollback(event_id)

Deciding *what* to change is **your** job, not the harness's. The host does not
lend us its model (no MCP sampling capability).
"""

from __future__ import annotations

from typing import Any

from .client import host_request

KINDS = ("prompt", "memory", "skill", "subagent")


class _Harness:
    async def overview(self) -> str:
        """Human-readable summary. The `[local:id]` ids it prints can be fed straight back."""
        return (await host_request("harness.overview"))["overview"]

    async def list(self, kind: str | None = None, *, scope: str = "all") -> list[dict[str, Any]]:
        return (await host_request("harness.list", {"kind": kind, "scope": scope}))["entries"]

    async def get(self, entry_id: str) -> dict[str, Any] | None:
        return (await host_request("harness.get", {"id": entry_id}))["entry"]

    async def create(
        self, kind: str, title: str, content: str, *, global_: bool = False, **kw
    ) -> dict[str, Any]:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}, got {kind!r}")
        payload = {"kind": kind, "title": title, "content": content, "global": global_, **kw}
        return (await host_request("harness.create", payload))["entry"]

    async def update(self, entry_id: str, **changes) -> dict[str, Any]:
        return (await host_request("harness.update", {"id": entry_id, **changes}))["entry"]

    async def delete(self, entry_id: str) -> dict[str, Any]:
        return (await host_request("harness.delete", {"id": entry_id}))["entry"]

    # ---------- refinement ----------

    async def evidence(self) -> dict[str, Any]:
        """Gather grounds from this session's record.

        Only `repeated_errors` are promotion candidates; a one-off is not a pattern.
        """
        return await host_request("harness.evidence")

    async def apply(
        self, changes: list[dict[str, Any]], *, trigger: str, evidence: str = ""
    ) -> dict[str, Any]:
        """Apply the minimal CRUD delta. If any change fails, the whole call reverts.

        Example `changes`:
            [{"op": "create", "kind": "prompt", "title": "...", "content": "..."},
             {"op": "update", "id": "ports", "content": "..."},
             {"op": "delete", "id": "stale-note"}]
        """
        payload = {"changes": changes, "trigger": trigger, "evidence": evidence}
        return (await host_request("harness.apply", payload))["event"]

    async def rollback(self, event_id: str) -> dict[str, Any]:
        return (await host_request("harness.rollback", {"event_id": event_id}))["event"]

    async def refinements(self) -> list[dict[str, Any]]:
        return (await host_request("harness.refinements"))["events"]

    # ---------- projection ----------

    async def project(self, *, agent: str = "auto", remove: bool = False) -> dict[str, Any]:
        """Export the harness into host-read files. Same behaviour as `opa_bootstrap`."""
        return await host_request("harness.project", {"agent": agent, "remove": remove})


harness = _Harness()
