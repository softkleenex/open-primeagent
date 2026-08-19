"""세션당 IPython 커널 하나를 소유한다.

부팅 시 주입하는 것:
  - `nest_asyncio` — 셀 최상단 `await` 를 가능하게 (원본과 동일 전제)
  - `opa_runtime` — `rlm` / `harness` / `goal` / `agent_message` 심볼
  - env: OPA_HOST_SOCKET, OPA_SESSION_DIR, OPA_ROLE=parent
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class KernelInfo:
    alive: bool
    pid: int | None
    started_at: str | None
    restarts: int


class KernelManager:
    def __init__(self, *, cwd: Path, socket_path: Path, session_dir: Path) -> None:
        self.cwd = cwd
        self.socket_path = socket_path
        self.session_dir = session_dir

    async def start(self) -> None:
        """커널을 띄우고 부트스트랩 셀을 실행한다."""
        raise NotImplementedError

    async def execute(self, code: str, *, timeout: float = 120.0) -> ExecResult:
        raise NotImplementedError

    async def interrupt(self) -> None:
        raise NotImplementedError

    async def restart(self) -> None:
        """사용자 변수는 사라진다. registry/harness/goal은 디스크에 있으므로 살아남는다."""
        raise NotImplementedError

    def info(self) -> KernelInfo:
        raise NotImplementedError


@dataclass
class ExecResult:
    ok: bool
    stdout: str
    result_repr: str | None
    error: str | None
    truncated: bool
    full_output_path: Path | None
    duration_ms: int
