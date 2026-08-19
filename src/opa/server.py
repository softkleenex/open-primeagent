"""MCP 서버 엔트리포인트.

노출 도구는 의도적으로 최대 4개다 (ARCHITECTURE §3):
    opa_python / opa_status / opa_kernel / opa_bootstrap(Phase 3)

rlm·harness·goal·agent_message는 도구가 아니라 커널 안의 Python 심볼이다.
호스트 에이전트의 도구 목록을 오염시키지 않는 것이 이 프로젝트의 전제다.
"""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from mcp.server.mcpserver import MCPServer

from . import __version__
from .config import Config
from .kernel.exec import store_full, strip_ansi, truncate
from .runtime_state import Runtime
from .tools import kernel_tool, python_tool, status_tool

# 도구 표면 상한. 늘리고 싶어지면 그건 커널 안 Python 심볼로 노출해야 한다는 신호다.
# tests/test_server.py 가 이 상한을 강제한다.
MAX_TOOLS = 4

INSTRUCTIONS = """\
open-primeagent gives you a persistent Python kernel as external working memory,
and lets you spawn long-lived sub-agent sessions from inside it.

Prefer opa_python over accumulating large tool output in your context: keep file
lists, search results and intermediate structures in Python variables, and print
only what you need in order to decide the next step.
"""


def build_server(config: Config | None = None) -> MCPServer:
    config = config or Config.from_env()
    runtime = Runtime(config)
    server = MCPServer(name="opa", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(name="opa_python", description=python_tool.DESCRIPTION)
    async def opa_python(code: str, timeout: float = 120.0) -> str:
        kernel = await runtime.kernel()
        result = await kernel.execute(code, timeout=timeout)

        parts: list[str] = []
        if result.stdout:
            parts.append(result.stdout.rstrip("\n"))
        if result.result_repr:
            parts.append(result.result_repr)
        if result.error:
            parts.append(strip_ansi(result.error))
        body = "\n".join(parts) if parts else "(no output)"

        full_path = None
        if len(body) > config.max_output_chars:
            full_path = store_full(runtime.paths.outputs, body)
        shown, was_truncated = truncate(body, config.max_output_chars, full_path=full_path)

        runtime.record(
            "python.exec",
            {
                "code": code,
                "ok": result.ok,
                "duration_ms": result.duration_ms,
                "output_chars": len(body),
                "truncated": was_truncated,
                "full_output": str(full_path) if full_path else None,
            },
        )
        status = "ok" if result.ok else "error"
        return f"[{status} · {result.duration_ms}ms]\n{shown}"

    @server.tool(name="opa_status", description=status_tool.DESCRIPTION)
    async def opa_status() -> str:
        kernel = runtime.kernel_if_started
        info = kernel.info() if kernel else None
        state = {
            "session_id": runtime.session_id,
            "session_dir": str(runtime.paths.dir),
            "workspace": str(config.workspace),
            "kernel": (
                {
                    "alive": info.alive,
                    "pid": info.pid,
                    "started_at": info.started_at,
                    "restarts": info.restarts,
                    "rlm_runtime_ok": info.runtime_ok,
                }
                if info
                else {"alive": False, "note": "not started yet — starts on first opa_python"}
            ),
            "subagents": [
                {
                    "name": r.name,
                    "adapter": r.adapter,
                    "status": r.status,
                    "turns": r.turns,
                    "tokens": r.tokens,
                    "cost_usd": r.cost_usd,
                    "last_error": r.last_error,
                }
                for r in runtime.rlm.registry.list()
            ],
            "mailbox_unread": runtime.rlm.mailbox.count(),
            "goal": {"note": "Phase 4"},
            "harness": {"note": "Phase 3"},
        }
        return json.dumps(state, indent=2, ensure_ascii=False)

    @server.tool(name="opa_kernel", description=kernel_tool.DESCRIPTION)
    async def opa_kernel(action: Literal["restart", "interrupt", "info"] = "info") -> str:
        kernel = await runtime.kernel()
        if action == "restart":
            await kernel.restart()
            runtime.record("kernel.restart", {})
            return (
                "kernel restarted — Python variables are gone. "
                "Sub-agents, harness and goal live on disk and survived."
            )
        if action == "interrupt":
            await kernel.interrupt()
            runtime.record("kernel.interrupt", {})
            return "interrupt sent"
        info = kernel.info()
        return json.dumps(info.__dict__, indent=2, default=str)

    server._opa_runtime = runtime  # 테스트/종료 처리에서 쓴다
    return server


def main() -> None:
    """stdio MCP 서버를 띄운다. `opa` 콘솔 스크립트의 진입점."""
    server = build_server()
    try:
        asyncio.run(server.run_stdio_async())
    finally:
        runtime = getattr(server, "_opa_runtime", None)
        if runtime is not None:
            asyncio.run(runtime.shutdown())


if __name__ == "__main__":
    main()
