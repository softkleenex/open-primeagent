"""`harness` — 커널에서 보이는 Continual Harness API.

    H = (ρ prompts, G subagents, K skills, M memory)

"self-improving"은 모델 weight가 아니라 **이 상태**가 개선되는 것이다.

    await harness.overview()
    await harness.create("prompt", "migration 후 generate", "pnpm prisma generate 실행")
    await harness.evidence()          # 무엇을 바꿀지 판단할 근거
    await harness.apply([...], trigger="...")   # 최소 CRUD delta 적용
    await harness.rollback(event_id)

무엇을 바꿀지 *판단*하는 것은 harness가 아니라 **당신**이다.
호스트는 우리에게 모델을 빌려주지 않는다 (MCP sampling 미지원).
"""

from __future__ import annotations

from typing import Any

from .client import host_request

KINDS = ("prompt", "memory", "skill", "subagent")


class _Harness:
    async def overview(self) -> str:
        """사람이 읽는 요약. `[local:id] title` 형태의 id를 그대로 다시 넣을 수 있다."""
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

    # ---------- 개선 ----------

    async def evidence(self) -> dict[str, Any]:
        """이번 세션 기록에서 근거를 모은다.

        `repeated_errors` 만 승격 후보다. 한 번 겪은 일은 올리지 않는다.
        """
        return await host_request("harness.evidence")

    async def apply(
        self, changes: list[dict[str, Any]], *, trigger: str, evidence: str = ""
    ) -> dict[str, Any]:
        """최소 CRUD delta를 적용한다. 하나라도 실패하면 통째로 되돌린다.

        changes 예:
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

    # ---------- 투영 ----------

    async def project(self, *, agent: str = "auto", remove: bool = False) -> dict[str, Any]:
        """harness를 호스트가 읽는 파일로 내보낸다. `opa_bootstrap` 과 같은 동작."""
        return await host_request("harness.project", {"agent": agent, "remove": remove})


harness = _Harness()
