"""`rlm` — 커널에서 보이는 API 표면. 원본과 동일한 모양을 유지한다.

    api = await rlm("API 보안 검토", name="api-reviewer")
    children = await rlm.list_subagents()
    await rlm.delete_subagent("api-reviewer")

`rlm(...)`은 결과를 기다리지 않는다. 핸들만 돌려주고 child는 계속 돈다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class RLMSpawnHandle:
    rlm_child_id: str
    name: str
    session_dir: Path
    model: str


@dataclass(frozen=True)
class RLMSubagent:
    rlm_child_id: str
    name: str
    adapter: str
    session_dir: Path
    status: Literal["running", "completed", "error"]
    turns: int


async def run(prompt: str, **kwargs: Any) -> RLMSpawnHandle:
    """독립된 에이전트 세션 하나를 만들고, admit 되는 즉시 반환한다.

    name    child의 주소. 나중에 agent_message로 다시 부를 때 쓴다.
    model   호스트 CLI에 그대로 넘긴다 (provider 레이어를 우리가 안 만드는 이유).
    adapter "claude-code" | "codex" | ... 생략 시 기본값.
    """
    raise NotImplementedError


class _RLM:
    async def run(self, prompt: str, **kwargs: Any) -> RLMSpawnHandle:
        return await run(prompt, **kwargs)

    async def list_subagents(self) -> list[RLMSubagent]:
        """커널 재시작·compaction 이후에도 이전 child들이 그대로 나와야 한다."""
        raise NotImplementedError

    async def delete_subagent(self, target: str) -> RLMSubagent:
        raise NotImplementedError

    async def find_models(self, query: str = "", limit: int = 8) -> list[dict]:
        raise NotImplementedError

    async def __call__(self, prompt: str, **kwargs: Any) -> RLMSpawnHandle:
        return await run(prompt, **kwargs)


rlm = _RLM()
