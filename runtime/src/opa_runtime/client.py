"""host_request - the only path from the kernel to the host.

    reply = await host_request("rlm.run", {"prompt": ..., "kwargs": {...}})

Reads $OPA_HOST_SOCKET. Child processes inherit that env, so they can call the
parent host through the same function - the precondition for two-way A2A.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
from typing import Any

ENV_SOCKET = "OPA_HOST_SOCKET"
# Says who is calling. The kernel and each child get different ones, and the
# bridge decides what each may do; holding the socket is not authority, because
# our own children hold it too.
ENV_TOKENS = ("OPA_CHILD_TOKEN",)

# The kernel's token is handed to it in-process at boot and never placed in its
# environment. `ps eww` shows any same-uid process another's environment, and the
# kernel token carries full authority -- a child with a shell could read it in
# one command and become the parent. Keeping it out of the environment does not
# make it unreachable (same-uid never is; see docs/security.md), it removes the
# one-command path.
_token: str | None = None


def set_token(value: str) -> None:
    global _token
    _token = value
DEFAULT_TIMEOUT = 300.0

# Must match the host (bridge.MAX_LINE_BYTES). Leaving asyncio's 64 KiB default
# breaks large replies, such as an inbox holding several child reports.
MAX_LINE_BYTES = 8 * 1024 * 1024

_ids = itertools.count(1)


async def host_request(
    request_type: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Send a typed request to the host and await its reply.

    Raises RuntimeError when the host reports an error or has no handler for the
    type.
    """
    if not isinstance(request_type, str) or not request_type:
        raise TypeError("request_type must be a non-empty str")
    if payload is not None and not isinstance(payload, dict):
        raise TypeError(f"payload must be a dict or None, got {type(payload).__name__}")

    socket_path = os.environ.get(ENV_SOCKET)
    if not socket_path:
        raise RuntimeError(
            "open-primeagent host bridge is unavailable "
            f"({ENV_SOCKET} is unset). This kernel was not started by the opa MCP server."
        )

    token = _token or next(
        (os.environ[name] for name in ENV_TOKENS if os.environ.get(name)), None
    )
    if not token:
        raise RuntimeError(
            "no open-primeagent caller token in the environment "
            "(no in-process token, and no OPA_CHILD_TOKEN). "
            "This process was not started by the opa server."
        )
    request = {
        "id": str(next(_ids)),
        "token": token,
        "type": request_type,
        "payload": payload or {},
    }

    async def _roundtrip() -> dict[str, Any]:
        reader, writer = await asyncio.open_unix_connection(socket_path, limit=MAX_LINE_BYTES)
        try:
            writer.write(json.dumps(request, ensure_ascii=False, default=str).encode() + b"\n")
            await writer.drain()
            raw = await reader.readline()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass

        if not raw:
            raise RuntimeError(f"host closed the connection without replying to {request_type}")

        reply = json.loads(raw)
        status = reply.get("status")
        if status == "ok":
            # Handler results arrive inside `result`, so they can never collide
            # with protocol keys.
            result = reply.get("result")
            return result if isinstance(result, dict) else {}
        if status == "error":
            raise RuntimeError(reply.get("error") or f"host request {request_type} failed")
        raise RuntimeError(f"host request {request_type} returned unexpected status: {status!r}")

    try:
        return await asyncio.wait_for(_roundtrip(), timeout=timeout)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"host bridge socket is gone ({socket_path}). The opa MCP server may have restarted."
        ) from exc
    except TimeoutError as exc:
        raise RuntimeError(f"host request {request_type} timed out after {timeout}s") from exc
