"""Environment-driven configuration.

Because we never modify the host agent, every setting arrives through the env of
the MCP server registration line and nowhere else.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Socket the kernel and child processes use to call the host (inherited by children)
ENV_HOST_SOCKET = "OPA_HOST_SOCKET"
ENV_SESSION_DIR = "OPA_SESSION_DIR"
ENV_ROLE = "OPA_ROLE"  # "parent" | "child"

# Measured: with only `--permission-mode acceptEdits`, a headless child cannot
# run a shell command at all -- it asks for an approval nobody is there to give,
# and reports back that it is blocked. It can still edit files, which produces
# the worst possible sub-agent: one that changes code and never runs the tests.
DEFAULT_CHILD_TOOLS = ("Bash", "Read", "Edit", "Write", "Grep", "Glob")
ENV_CHILD_NAME = "OPA_CHILD_NAME"


@dataclass(frozen=True)
class Config:
    root: Path                 # per-project state root (default <cwd>/.opa)
    global_root: Path          # state shared across projects (default ~/.opa)
    workspace: Path            # the host agent's working directory
    max_output_chars: int      # how much output opa_python puts in its reply
    default_adapter: str       # "claude-code" | "codex" | ...
    child_permission_mode: str # conservative default; bypass is explicit opt-in only
    child_allowed_tools: tuple[str, ...]  # a child that cannot run tests is half a sub-agent
    allow_dangerous_child: bool
    child_can_message_parent: bool  # attach the one-tool opa-child server

    @classmethod
    def from_env(cls) -> Config:
        workspace = Path(os.environ.get("OPA_WORKSPACE", os.getcwd())).resolve()
        return cls(
            root=Path(os.environ.get("OPA_ROOT", workspace / ".opa")).resolve(),
            global_root=Path(
                os.environ.get("OPA_GLOBAL_ROOT", Path.home() / ".opa")
            ).expanduser().resolve(),
            workspace=workspace,
            max_output_chars=int(os.environ.get("OPA_MAX_OUTPUT_CHARS", "4000")),
            default_adapter=os.environ.get("OPA_DEFAULT_ADAPTER", "claude-code"),
            child_permission_mode=os.environ.get("OPA_CHILD_PERMISSION_MODE", "acceptEdits"),
            child_allowed_tools=tuple(
                part.strip()
                for part in os.environ.get(
                    "OPA_CHILD_ALLOWED_TOOLS", ",".join(DEFAULT_CHILD_TOOLS)
                ).split(",")
                if part.strip()
            ),
            allow_dangerous_child=os.environ.get("OPA_ALLOW_DANGEROUS_CHILD") == "1",
            child_can_message_parent=os.environ.get("OPA_CHILD_PUSH", "1") != "0",
        )
