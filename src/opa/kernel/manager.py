"""세션당 IPython 커널 하나를 소유한다.

부팅 시 주입하는 것:
  - `opa_runtime` — `rlm` / `harness` / `goal` / `agent_message` 심볼
  - env: OPA_HOST_SOCKET, OPA_SESSION_DIR, OPA_ROLE=parent

top-level `await`는 IPython의 autoawait가 네이티브로 처리한다.
(원본은 nest_asyncio를 쓰지만 실측 결과 불필요했다.)

커널은 **이 서버와 같은 인터프리터**로 띄운다. 사용자 시스템의 kernelspec에
의존하면 opa_runtime이 없는 파이썬으로 커널이 떠서 rlm 심볼이 사라진다.
그래서 kernelspec을 세션 디렉터리에 직접 써서 argv를 sys.executable로 고정한다.
"""

from __future__ import annotations

import json
import os
import queue
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jupyter_client.kernelspec import KernelSpecManager
from jupyter_client.manager import AsyncKernelManager

KERNEL_NAME = "opa-python"
_UNIX_SOCKET_PATH_MAX = 100  # macOS sun_path 104 - 여유

# 커널 부팅 직후 실행되는 셀. 실패해도 커널은 살아있어야 하므로 조용히 넘긴다
# (rlm 없이도 순수 Python 작업 메모리로는 쓸 수 있다).
BOOTSTRAP = """\
try:
    from opa_runtime import rlm, host_request  # noqa: F401
    _OPA_RUNTIME_OK = True
except Exception as _opa_exc:  # pragma: no cover
    _OPA_RUNTIME_OK = False
    _OPA_RUNTIME_ERROR = repr(_opa_exc)
"""


@dataclass
class KernelInfo:
    alive: bool
    pid: int | None
    started_at: str | None
    restarts: int
    runtime_ok: bool | None = None


@dataclass
class ExecResult:
    ok: bool
    stdout: str
    result_repr: str | None
    error: str | None
    truncated: bool
    full_output_path: Path | None
    duration_ms: int


def _now() -> str:
    return datetime.now(UTC).isoformat()


class KernelManager:
    def __init__(self, *, cwd: Path, socket_path: Path, session_dir: Path) -> None:
        self.cwd = cwd
        self.socket_path = socket_path
        self.session_dir = session_dir
        self._km: AsyncKernelManager | None = None
        self._kc = None
        self._started_at: str | None = None
        self._restarts = 0
        self._runtime_ok: bool | None = None

    # ---------- kernelspec ----------

    def _write_kernelspec(self) -> Path:
        """argv를 sys.executable로 고정한 kernelspec을 세션 디렉터리에 쓴다."""
        spec_root = self.session_dir / "kernelspec"
        spec_dir = spec_root / KERNEL_NAME
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "kernel.json").write_text(
            json.dumps(
                {
                    "argv": [
                        sys.executable,
                        "-m",
                        "ipykernel_launcher",
                        "-f",
                        "{connection_file}",
                    ],
                    "display_name": "open-primeagent",
                    "language": "python",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return spec_root

    def _transport(self) -> tuple[str, str]:
        """(transport, ip) 를 고른다.

        TCP는 커널 코드/출력을 로컬 평문으로 흘린다 (ipykernel 스스로 경고한다).
        POSIX에서는 파일 권한으로 보호되는 IPC 소켓을 쓴다. 단 unix 소켓 경로는
        macOS에서 104바이트 제한이 있고 jupyter_client는 ip를 경로 프리픽스로
        쓰므로(`<ip>-1` ~ `<ip>-5`), 길면 TCP로 물러난다.
        """
        if os.name != "posix":
            return "tcp", "127.0.0.1"
        prefix = Path(tempfile.gettempdir()) / f"opa-{uuid.uuid4().hex[:8]}"
        if len(str(prefix)) + 2 > _UNIX_SOCKET_PATH_MAX:
            return "tcp", "127.0.0.1"
        return "ipc", str(prefix)

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["OPA_HOST_SOCKET"] = str(self.socket_path)
        env["OPA_SESSION_DIR"] = str(self.session_dir)
        env["OPA_ROLE"] = "parent"
        return env

    # ---------- lifecycle ----------

    async def start(self) -> None:
        """커널을 띄우고 부트스트랩 셀을 실행한다."""
        spec_root = self._write_kernelspec()
        ksm = KernelSpecManager()
        ksm.kernel_dirs = [str(spec_root)]

        transport, ip = self._transport()
        self._km = AsyncKernelManager(
            kernel_name=KERNEL_NAME, kernel_spec_manager=ksm, transport=transport, ip=ip
        )
        await self._km.start_kernel(cwd=str(self.cwd), env=self._env())
        self._kc = self._km.client()
        self._kc.start_channels()
        await self._kc.wait_for_ready(timeout=60)
        self._started_at = _now()

        boot = await self.execute(BOOTSTRAP, timeout=30, record_output=False)
        probe = await self.execute("_OPA_RUNTIME_OK", timeout=10, record_output=False)
        self._runtime_ok = boot.ok and probe.result_repr == "True"

    async def stop(self) -> None:
        if self._kc is not None:
            self._kc.stop_channels()
            self._kc = None
        if self._km is not None:
            await self._km.shutdown_kernel(now=True)
            self._km = None

    async def restart(self) -> None:
        """사용자 변수는 사라진다. registry/harness/goal은 디스크에 있으므로 살아남는다."""
        if self._km is None:
            await self.start()
            return
        await self._km.restart_kernel(now=True)
        await self._kc.wait_for_ready(timeout=60)
        self._restarts += 1
        self._started_at = _now()
        boot = await self.execute(BOOTSTRAP, timeout=30, record_output=False)
        probe = await self.execute("_OPA_RUNTIME_OK", timeout=10, record_output=False)
        self._runtime_ok = boot.ok and probe.result_repr == "True"

    async def interrupt(self) -> None:
        if self._km is not None:
            await self._km.interrupt_kernel()

    def info(self) -> KernelInfo:
        alive = self._km is not None
        pid = None
        if self._km is not None and self._km.provisioner is not None:
            pid = getattr(self._km.provisioner, "pid", None)
        return KernelInfo(
            alive=alive,
            pid=pid,
            started_at=self._started_at,
            restarts=self._restarts,
            runtime_ok=self._runtime_ok,
        )

    # ---------- execution ----------

    async def execute(
        self,
        code: str,
        *,
        timeout: float = 120.0,
        record_output: bool = True,
    ) -> ExecResult:
        if self._kc is None:
            raise RuntimeError("kernel is not started")

        started = time.monotonic()
        msg_id = self._kc.execute(code, store_history=True, allow_stdin=False)

        stdout_parts: list[str] = []
        result_repr: str | None = None
        error: str | None = None
        deadline = started + timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                await self.interrupt()
                error = f"TimeoutError: cell exceeded {timeout}s and was interrupted"
                break
            try:
                msg = await self._kc.get_iopub_msg(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue

            if msg.get("parent_header", {}).get("msg_id") != msg_id:
                continue

            mtype = msg["msg_type"]
            content = msg["content"]
            if mtype == "stream":
                stdout_parts.append(content.get("text", ""))
            elif mtype in ("execute_result", "display_data"):
                text = content.get("data", {}).get("text/plain")
                if text is not None:
                    result_repr = text
            elif mtype == "error":
                error = "\n".join(content.get("traceback", [])) or content.get("evalue", "")
            elif mtype == "status" and content.get("execution_state") == "idle":
                break

        duration_ms = int((time.monotonic() - started) * 1000)
        return ExecResult(
            ok=error is None,
            stdout="".join(stdout_parts),
            result_repr=result_repr,
            error=error,
            truncated=False,          # 잘라내기는 도구 계층에서 (Config를 아는 쪽)
            full_output_path=None,
            duration_ms=duration_ms,
        )
