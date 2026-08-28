"""MCP server entry point.

The exposed tool surface is deliberately capped at four (ARCHITECTURE section 3):
    opa_python / opa_status / opa_kernel / opa_bootstrap(Phase 3)

`rlm`, `harness`, `goal` and `agent_message` are Python symbols inside the
kernel, not tools. Not polluting the host's tool list is a premise here.
"""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context

from . import __version__
from .config import Config
from .kernel.exec import store_full, strip_ansi, truncate
from .runtime_state import Runtime
from .tools import bootstrap_tool, kernel_tool, python_tool, status_tool
from .tools.surface import ToolSurface

# The ceiling on the tool surface. Wanting to raise it is the signal to expose a
# kernel symbol instead. tests/test_server.py enforces it.
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

    surface = ToolSurface(server, "opa_python", python_tool.DESCRIPTION)
    runtime.surface = surface

    @server.tool(name="opa_python", description=python_tool.DESCRIPTION)
    async def opa_python(code: str, timeout: float = 120.0, ctx: Context | None = None) -> str:
        # The connection is how a harness change reaches the host mid-session:
        # rewriting this tool's own description and asking it to re-read.
        runtime.connection = getattr(ctx, "connection", None) if ctx else None
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

    surface.bind(opa_python)
    # Nothing is rendered at startup on purpose: a fresh process has recorded
    # nothing yet, and a note it cannot remember making carries no authority
    # (see Runtime.pending_prompt_entries). Older notes reach the agent through
    # the project file, or when it asks with harness.overview().

    @server.tool(name="opa_status", description=status_tool.DESCRIPTION)
    async def opa_status() -> str:
        kernel = runtime.kernel_if_started
        info = kernel.info() if kernel else None
        # What is still callable matters more than what was stored. Upstream
        # re-anchors a compacted agent with exactly this list.
        names = await kernel.namespace() if kernel else []
        state = {
            "attention": runtime.attention(),
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
            "kernel_names": names,
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
            "goal": runtime.goals.get(),
            "schedule": {
                "entries": len(runtime.schedule.list()),
                "due_now": len(runtime.schedule.due(collect=False)),
            },
            "autonomous": runtime.autonomous.status(),
            "harness": runtime.harness.snapshot(),
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

    @server.tool(name="opa_bootstrap", description=bootstrap_tool.DESCRIPTION)
    async def opa_bootstrap(agent: str = "auto", remove: bool = False) -> str:
        result = runtime.bootstrap(agent=agent, remove=remove)
        if remove:
            removed = result["removed"]
            return (
                "removed the open-primeagent block from: " + ", ".join(removed)
                if removed
                else "nothing to remove — no opa block was present"
            )
        lines = [f"projected harness for: {', '.join(result['agents'])}"]
        for label, key in (("updated", "updated"), ("already current", "unchanged")):
            if result[key]:
                lines.append(f"  {label}: {', '.join(result[key])}")
        if result["skills"]:
            lines.append(f"  skills: {len(result['skills'])}")
        if result["memories"]:
            lines.append(f"  memories: {len(result['memories'])}")
        lines.append("  (writes happen only inside the opa delimiter block)")
        return "\n".join(lines)

    server._opa_runtime = runtime  # used by tests and by shutdown
    return server


def main() -> None:
    """Run the stdio MCP server. Entry point for the `opa` console script."""
    server = build_server()
    try:
        asyncio.run(server.run_stdio_async())
    finally:
        runtime = getattr(server, "_opa_runtime", None)
        if runtime is not None:
            asyncio.run(runtime.shutdown())


if __name__ == "__main__":
    main()
