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
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

from .base import TurnRequest, TurnResult

CLI = "claude"
CHILD_SERVER_NAME = "opa_child"

# What a coding CLI needs to start and find its own configuration. Everything
# else the server happens to hold stays with the server.
BASE_ENV = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "TERM",
    "TMPDIR", "TEMP", "TMP", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
    "CLAUDE_CONFIG_DIR", "CODEX_HOME", "NODE_EXTRA_CA_CERTS",
)


def _passthrough() -> tuple[str, ...]:
    """Extra variables the user has explicitly chosen to forward to children."""
    raw = os.environ.get("OPA_CHILD_ENV_PASSTHROUGH", "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())
CHILD_PUSH_TOOL = f"mcp__{CHILD_SERVER_NAME}__opa_notify_parent"


def write_child_mcp_config(session_dir: Path) -> Path:
    """A config attaching only the one-tool `opa-child` server.

    Never the full opa server: a child with `rlm` could spawn grandchildren, and
    each one costs a full session startup.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / "child-mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    CHILD_SERVER_NAME: {
                        "command": sys.executable,
                        "args": ["-m", "opa.child_server"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


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
        allowed = list(request.allowed_tools)
        # `--mcp-config` is *additive*: without `--strict-mcp-config` a child also
        # loads every MCP server the user has registered -- their mail, their
        # drive, their browser, and in a workspace where opa itself is registered,
        # a full opa server with a parent-role token. A spawned sub-agent must
        # start from nothing and be handed only what we chose to give it.
        cmd += ["--strict-mcp-config"]
        if request.can_message_parent:
            cmd += ["--mcp-config", str(write_child_mcp_config(request.session_dir))]
            allowed.append(CHILD_PUSH_TOOL)
        if allowed and not request.allow_dangerous:
            # Without this a headless child is blocked on an approval prompt for
            # every shell command, so it edits code it can never test.
            cmd += ["--allowedTools", ",".join(allowed)]
        return cmd

    def _env(self, request: TurnRequest) -> dict[str, str]:
        """Build the child's environment, rather than handing it ours.

        Copying `os.environ` wholesale gave a child every secret the server
        happened to hold -- cloud credentials, tokens for other MCP servers --
        and a prompt-injected child with a shell only has to run `env`. It needs
        far less than that: enough to find its CLI and its own config.

        The socket is passed explicitly because it lives on the *kernel's*
        environment, not the server's, so inheriting alone left children unable
        to answer back at all.
        """
        env = {
            name: os.environ[name]
            for name in (*BASE_ENV, *_passthrough())
            if name in os.environ
        }
        env["OPA_ROLE"] = "child"
        if request.child_name:
            env["OPA_CHILD_NAME"] = request.child_name
        if request.host_socket:
            env["OPA_HOST_SOCKET"] = request.host_socket
        if request.token:
            env["OPA_CHILD_TOKEN"] = request.token
        return env

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
