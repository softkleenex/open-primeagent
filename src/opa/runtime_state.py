"""서버 프로세스가 들고 있는 상태 — 세션, 커널, (Phase 2부터) registry/harness.

커널은 **지연 부팅**한다. 호스트가 MCP 서버를 띄웠다는 이유만으로 커널을
올릴 필요는 없다. 첫 `opa_python` 호출에서 올린다.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .config import Config
from .kernel.manager import KernelManager
from .session import jsonl
from .session.paths import SessionPaths


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Runtime:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.session_id = uuid.uuid4().hex
        self.paths = SessionPaths(root=config.root, session_id=self.session_id).ensure()
        self.started_at = _now()
        self._kernel: KernelManager | None = None
        self._lock = asyncio.Lock()
        self.paths.meta.write_text(
            f'{{"session_id": "{self.session_id}", "started_at": "{self.started_at}",'
            f' "workspace": "{config.workspace}"}}\n',
            encoding="utf-8",
        )

    @property
    def socket_path(self) -> Path:
        return self.paths.dir / "host.sock"

    async def kernel(self) -> KernelManager:
        """첫 호출에서 커널을 부팅한다. 동시 호출은 한 번만 부팅되게 잠근다."""
        async with self._lock:
            if self._kernel is None:
                km = KernelManager(
                    cwd=self.config.workspace,
                    socket_path=self.socket_path,
                    session_dir=self.paths.dir,
                )
                await km.start()
                self._kernel = km
                self.record("kernel.start", {"runtime_ok": km.info().runtime_ok})
        return self._kernel

    @property
    def kernel_if_started(self) -> KernelManager | None:
        return self._kernel

    def record(self, event: str, data: dict) -> None:
        """trajectory 기록. /refine의 입력이 된다."""
        jsonl.append(self.paths.trajectory, {"at": _now(), "event": event, **data})

    async def shutdown(self) -> None:
        if self._kernel is not None:
            await self._kernel.stop()
            self._kernel = None
