"""Owns exactly one IPython kernel per session.

Injected at boot:
  - `opa_runtime` - `rlm` / `harness` / `agent_message` / `goal` / `schedule` /
    `autonomous`
  - env: OPA_HOST_SOCKET, OPA_SESSION_DIR, OPA_ROLE=parent

Top-level `await` is handled natively by IPython's autoawait. Upstream uses
nest_asyncio; measuring showed it is unnecessary here.

The kernel runs under **this server's interpreter**. Relying on the user's
installed kernelspec would boot a Python without `opa_runtime`, and the `rlm`
symbols would silently disappear. So we write our own kernelspec into the
session directory with argv pinned to sys.executable.
"""

from __future__ import annotations

import ast
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
from typing import Any

KERNEL_NAME = "opa-python"
_UNIX_SOCKET_PATH_MAX = 100  # macOS sun_path is 104; leave headroom

# The cell run right after boot. It must not take the kernel down on failure -
# even without `rlm`, a plain Python working memory is still useful.
BOOTSTRAP = """\
try:
    from opa_runtime import (  # noqa: F401
        agent_message,
        autonomous,
        goal,
        harness,
        host_request,
        rlm,
        schedule,
    )
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
    def __init__(
        self, *, cwd: Path, socket_path: Path, session_dir: Path, token: str = ""
    ) -> None:
        self.cwd = cwd
        self.socket_path = socket_path
        self.session_dir = session_dir
        self.token = token
        self._km: Any | None = None
        self._kc = None
        self._started_at: str | None = None
        self._restarts = 0
        self._runtime_ok: bool | None = None

    # ---------- kernelspec ----------

    def _write_kernelspec(self) -> Path:
        """Write a kernelspec whose argv is pinned to sys.executable."""
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
        """Choose (transport, ip).

        TCP sends kernel code and output in cleartext over localhost - ipykernel
        warns about this itself. On POSIX we use an IPC socket protected by file
        permissions. But unix socket paths are capped at 104 bytes on macOS and
        jupyter_client uses `ip` as the path prefix (`<ip>-1` .. `<ip>-5`), so we
        fall back to TCP when the path would not fit.
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
        if self.token:
            env["OPA_HOST_TOKEN"] = self.token
        return env

    # ---------- lifecycle ----------

    async def start(self) -> None:
        """Boot the kernel and run the bootstrap cell.

        `jupyter_client` is imported here rather than at module scope. It pulls
        in zmq and jupyter_core and costs real startup time, and the kernel is
        deliberately lazy - a host that registers the server but never runs
        Python should not pay for it.
        """
        from jupyter_client.kernelspec import KernelSpecManager
        from jupyter_client.manager import AsyncKernelManager

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
        """User variables are lost. Registry, harness and goal live on disk and survive."""
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

    async def namespace(self, limit: int = 40) -> list[str]:
        """User-defined names currently live in the kernel.

        After a host loses context this is the single most useful fact we hold:
        not what was stored, but what is still *callable*. Upstream re-anchors a
        compacted agent with exactly this list.

        Returns an empty list when no kernel is running - asking must not start one.
        """
        if self._kc is None:
            return []
        code = (
            "print(repr(sorted(n for n in globals() "
            "if not n.startswith('_') and n not in "
            "('In','Out','exit','quit','get_ipython','open'))))"
        )
        result = await self.execute(code, timeout=10, record_output=False)
        if not result.ok:
            return []
        try:
            names = ast.literal_eval(result.stdout.strip())
        except (SyntaxError, ValueError):
            return []
        return [n for n in names if isinstance(n, str)][:limit]

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
            truncated=False,          # truncation happens in the tool layer, which knows Config
            full_output_path=None,
            duration_ms=duration_ms,
        )
