"""opa_runtime - the shim that lives inside the kernel.

It corresponds to upstream `prime-agent-runtime`'s `rlm` package; only the
transport differs. Upstream calls a TypeScript host over a Jupyter comm, we call
an MCP server over a Unix socket. The API surface and request type names match
upstream so its docs and skills still apply.

At kernel boot this module exposes `rlm`, `agent_message`, `harness`,
`goal`, `schedule` and `autonomous`.
"""

from __future__ import annotations

from .client import host_request
from .harness import harness
from .longrun import autonomous, goal, schedule
from .message import agent_message
from .rlm import RLMSpawnHandle, RLMSubagent, rlm

__all__ = [
    "RLMSpawnHandle",
    "RLMSubagent",
    "agent_message",
    "autonomous",
    "goal",
    "harness",
    "host_request",
    "rlm",
    "schedule",
]
