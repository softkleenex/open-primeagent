"""Claude Code adapter (the default).

    spawn :  claude -p <PROMPT> --session-id <UUID> --output-format json
    resume:  claude -p <PROMPT> --resume <UUID>     --output-format json

Being able to **issue the session UUID ourselves** matters: the registry id and
the native session id map 1:1, which keeps recovery trivial.

Measured 2026-08-19: a `--resume`d turn remembers the turn before it. That is
the basis for "a child is not disposable".

Security: `--dangerously-skip-permissions` only when Config.allow_dangerous_child.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
import uuid

from .base import TurnRequest, TurnResult

CLI = "claude"


class ClaudeCodeAdapter:
    name = "claude-code"

    def available(self) -> bool:
        return shutil.which(CLI) is not None

    def preassign_session_id(self) -> str | None:
        return str(uuid.uuid4())

    def build_command(self, request: TurnRequest) -> list[str]:
        cmd = [CLI, "-p", request.prompt, "--output-format", "json"]
        if request.resume:
            cmd += ["--resume", request.session_id or ""]
        else:
            cmd += ["--session-id", request.session_id or str(uuid.uuid4())]
        if request.model:
            cmd += ["--model", request.model]
        if request.system_prompt:
            cmd += ["--append-system-prompt", request.system_prompt]
        if request.allow_dangerous:
            cmd += ["--dangerously-skip-permissions"]
        else:
            cmd += ["--permission-mode", request.permission_mode]
        return cmd

    async def run(self, request: TurnRequest) -> TurnResult:
        started = time.monotonic()
        cmd = self.build_command(request)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(request.cwd),
            # Close stdin - left open as a pipe, the CLI reads it as extra input.
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=request.timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return TurnResult(
                ok=False,
                text="",
                session_id=request.session_id,
                error=f"child timed out after {request.timeout}s",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        raw_path = request.session_dir / f"turn-{int(time.time() * 1000)}.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(stdout or b"")

        if proc.returncode != 0 and not stdout:
            return TurnResult(
                ok=False,
                text="",
                session_id=request.session_id,
                error=(stderr or b"").decode(errors="replace").strip()[:2000]
                or f"{CLI} exited with {proc.returncode}",
                raw_path=raw_path,
                duration_ms=duration_ms,
            )

        return self.parse_result(stdout, request, raw_path, duration_ms)

    def parse_result(self, stdout, request, raw_path, duration_ms) -> TurnResult:
        try:
            payload = json.loads(stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            return TurnResult(
                ok=False,
                text=(stdout or b"").decode(errors="replace")[:2000],
                session_id=request.session_id,
                error=f"could not parse {CLI} output: {exc}",
                raw_path=raw_path,
                duration_ms=duration_ms,
            )

        usage = payload.get("usage") or {}
        tokens = None
        if usage:
            # Cache creation is billed and is most of a fresh child session's cost
            # (system prompt + tool schemas). Leaving it out made opa_status
            # under-report a child by roughly an order of magnitude.
            tokens = (
                int(usage.get("input_tokens", 0))
                + int(usage.get("output_tokens", 0))
                + int(usage.get("cache_creation_input_tokens", 0))
            )
        is_error = bool(payload.get("is_error")) or payload.get("subtype") not in (None, "success")
        return TurnResult(
            ok=not is_error,
            text=payload.get("result") or "",
            session_id=payload.get("session_id") or request.session_id,
            tokens=tokens,
            cost_usd=payload.get("total_cost_usd"),
            raw_path=raw_path,
            error=payload.get("api_error_status") if is_error else None,
            duration_ms=duration_ms,
        )
