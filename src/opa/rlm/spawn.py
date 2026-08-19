"""`rlm.run` 핸들러.

중요: **결과를 기다리지 않는다.** 원본과 동일하게 task가 admit된 시점에
핸들을 반환하고, child는 백그라운드에서 계속 돈다. 결과는 메일박스로 온다.
그래서 아래 두 줄이 순차 대기 없이 진짜로 병렬이다:

    api  = await rlm("...", name="api-reviewer")
    test = await rlm("...", name="test-reviewer")
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpawnSpec:
    prompt: str
    name: str
    cwd: Path
    model: str | None = None
    adapter: str | None = None      # None이면 Config.default_adapter
    system_prompt: str | None = None
    thinking: str | None = None


@dataclass(frozen=True)
class SpawnHandle:
    rlm_child_id: str
    name: str
    session_dir: Path
    model: str


class Spawner:
    async def run(self, spec: SpawnSpec) -> SpawnHandle:
        """어댑터로 child를 띄우고 registry에 등록한 뒤 즉시 반환."""
        raise NotImplementedError
