"""`rlm` — 커널에서 보이는 API 표면. 원본과 동일한 모양을 유지한다.

    api = await rlm("API 보안 검토", name="api-reviewer")
    children = await rlm.list_subagents()
    await rlm.delete_subagent("api-reviewer")

`rlm(...)`은 결과를 기다리지 않는다. 핸들만 돌려주고 child는 계속 돈다.
결과는 `await agent_message.inbox()` 로 수거한다.
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
    """독립된 에이전트 세션 하나를 만들고, admit 되는 즉시 반환한다.

    name     child의 주소. 나중에 agent_message로 다시 부를 때 쓴다. **필수**.
    model    호스트 CLI에 그대로 넘긴다 (provider 레이어를 우리가 안 만드는 이유).
    adapter  "claude-code" | "codex". 생략 시 기본값.
    cwd      workspace 하위 경로만 허용된다.
    system_prompt  child에게 상시 부여할 역할 스펙.
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
        """커널 재시작·compaction 이후에도 이전 child들이 그대로 나와야 한다."""
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
