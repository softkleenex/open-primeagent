"""Codex adapter.

    spawn :  codex exec <PROMPT> --json --skip-git-repo-check [-m MODEL]
    resume:  codex exec resume <THREAD_ID> <PROMPT> --json

Unlike claude we cannot choose the session id - it is parsed from the first
run's `thread.started` event and stored in the registry.

Two constraints found by running it (2026-08-19):
  1. **stdin must be closed.** Left open as a pipe, codex waits forever at
     "Reading additional input from stdin...".
  2. Outside a git repository it refuses to run without `--skip-git-repo-check`.

JSONL event schema:
    {"type":"thread.started","thread_id":"..."}
    {"type":"item.completed","item":{"type":"agent_message","text":"..."}}
    {"type":"turn.completed","usage":{"input_tokens":N,"output_tokens":N,...}}
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time

from .base import TurnRequest, TurnResult
from .claude_code import CHILD_SERVER_NAME

CLI = "codex"

# Default sandbox: no writes outside the workspace (docs/security.md).
DEFAULT_SANDBOX = "workspace-write"


class CodexAdapter:
    name = "codex"

    def available(self) -> bool:
        return shutil.which(CLI) is not None

    def preassign_session_id(self) -> str | None:
        return None  # codex issues it

    def build_command(self, request: TurnRequest) -> list[str]:
        if request.resume:
            if not request.session_id:
                raise ValueError("cannot resume a codex session without a thread id")
            cmd = [CLI, "exec", "resume", request.session_id, request.prompt]
        else:
            cmd = [CLI, "exec", request.prompt]
        cmd += ["--json", "--skip-git-repo-check"]
        if request.model:
            cmd += ["-m", request.model]
        if request.allow_dangerous:
            cmd += ["--dangerously-bypass-approvals-and-sandbox"]
        else:
            cmd += ["--sandbox", DEFAULT_SANDBOX]
        if self.push_available(request):
            # codex has no --mcp-config; servers are config keys, and `-c` takes
            # TOML, so each value has to be quoted as TOML rather than as JSON.
            cmd += [
                "-c", f'mcp_servers.{CHILD_SERVER_NAME}.command={json.dumps(sys.executable)}',
                "-c", f'mcp_servers.{CHILD_SERVER_NAME}.args=["-m", "opa.child_server"]',
            ]
        return cmd

    @staticmethod
    def push_available(request: TurnRequest) -> bool:
        """Whether attaching the push server is worth doing for this turn.

        Measured (2026-08-28): in headless `codex exec`, an MCP tool call comes
        back as `user cancelled MCP tool call` unless the run also passes
        `--dangerously-bypass-approvals-and-sandbox`. Neither `approval_policy`,
        `mcp_servers.<name>.trust` nor `.enabled` changes that -- the approval
        policy governs shell commands, not MCP tools, and headless has no channel
        to approve on.

        So a sandboxed codex child would be handed a tool that always fails,
        paying for its schema and getting a confusing cancellation back. Better
        to leave it off and say so.
        """
        return request.can_message_parent and request.allow_dangerous

    def _env(self, request: TurnRequest) -> dict[str, str]:
        """The child inherits the host socket; without it it cannot answer back."""
        env = dict(os.environ)
        env["OPA_ROLE"] = "child"
        if request.child_name:
            env["OPA_CHILD_NAME"] = request.child_name
        if request.host_socket:
            env["OPA_HOST_SOCKET"] = request.host_socket
        return env

    async def run(self, request: TurnRequest) -> TurnResult:
        started = time.monotonic()
        cmd = self.build_command(request)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(request.cwd),
            # stdin must be closed; left open, codex blocks waiting on it.
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env(request),
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
        raw_path = request.session_dir / f"turn-{int(time.time() * 1000)}.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(stdout or b"")

        result = self.parse_stream(stdout, request, raw_path, duration_ms)
        if not result.text and proc.returncode != 0:
            return TurnResult(
                ok=False,
                text="",
                session_id=result.session_id,
                error=(stderr or b"").decode(errors="replace").strip()[:2000]
                or f"{CLI} exited with {proc.returncode}",
                raw_path=raw_path,
                duration_ms=duration_ms,
            )
        return result

    def parse_stream(self, stdout, request, raw_path, duration_ms) -> TurnResult:
        session_id = request.session_id
        text = ""
        tokens = None
        for line in (stdout or b"").decode(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "thread.started":
                session_id = event.get("thread_id") or session_id
            elif kind == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message" and item.get("text"):
                    text = item["text"]  # the last agent_message is the final answer
            elif kind == "turn.completed":
                usage = event.get("usage") or {}
                if usage:
                    # cached_input_tokens is reported separately and is still billed
                    tokens = (
                        int(usage.get("input_tokens", 0))
                        + int(usage.get("output_tokens", 0))
                        + int(usage.get("cache_write_input_tokens", 0))
                    )
        return TurnResult(
            ok=bool(text),
            text=text,
            session_id=session_id,
            tokens=tokens,
            raw_path=raw_path,
            error=None if text else "codex produced no agent_message",
            duration_ms=duration_ms,
        )
