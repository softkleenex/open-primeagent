"""HostBridge - the door through which the kernel, skills and children call the host.

Upstream uses a Jupyter comm (`host.request`); we use a Unix domain socket.
See ARCHITECTURE section 2: the socket is independent of kernel restarts, and
processes that are not the kernel (skill subprocesses, child agents) can use the
same door.

Protocol: one request per connection, one line of JSON.
    →  {"id": "1", "type": "rlm.run", "payload": {...}}
    ←  {"id": "1", "status": "ok",    "result": {...}}
    ←  {"id": "1", "status": "error", "error": "..."}

Handler results are **wrapped in `result`**. Merging them flat lets a handler's
own `status` key shadow the protocol's - and it did: `rlm.run` returned
`status: "running"`, which overwrote `status: "ok"` and broke the client.
A naming convention would break again later, so this is made structurally
impossible instead.

Request type names match upstream (rlm.run / rlm.list_subagents /
rlm.delete_subagent / rlm.find_models) so upstream docs and skills still apply.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

# Per-line ceiling, so the kernel cannot kill the host with a giant payload.
#
# asyncio's StreamReader defaults to 64 KiB. Without raising it, prompts larger
# than 64 KB (a review request carrying a diff) and inboxes larger than 64 KB
# (several child reports) simply break. Both **server and client** must set it.
MAX_LINE_BYTES = 8 * 1024 * 1024


class HostBridge:
    """Listen on the socket and dispatch by request type."""

    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path
        self._handlers: dict[str, Handler] = {}
        self._server: asyncio.AbstractServer | None = None

    def register(self, request_type: str, handler: Handler) -> None:
        """Attach a handler to a type such as `rlm.run`."""
        if request_type in self._handlers:
            raise ValueError(f"handler for {request_type!r} is already registered")
        self._handlers[request_type] = handler

    @property
    def types(self) -> list[str]:
        return sorted(self._handlers)

    async def serve(self) -> None:
        """Start accepting connections. Must be up before the kernel starts."""
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle, path=str(self.socket_path), limit=MAX_LINE_BYTES
        )
        # Stop another local user from pushing commands into the kernel.
        os.chmod(self.socket_path, 0o600)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self.socket_path.exists():
            self.socket_path.unlink()

    # ---------- internals ----------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request_id = None
        try:
            try:
                raw = await reader.readline()
            except ValueError:
                return await self._reply(
                    writer, None, error=f"request exceeds the {MAX_LINE_BYTES:,}-byte limit"
                )
            if not raw:
                return

            try:
                request = json.loads(raw)
            except json.JSONDecodeError as exc:
                return await self._reply(writer, None, error=f"invalid JSON: {exc}")
            if not isinstance(request, dict):
                return await self._reply(writer, None, error="request must be a JSON object")

            request_id = request.get("id")
            request_type = request.get("type")
            if not isinstance(request_type, str) or not request_type:
                return await self._reply(writer, request_id, error="request is missing 'type'")

            handler = self._handlers.get(request_type)
            if handler is None:
                known = ", ".join(self.types) or "(none)"
                return await self._reply(
                    writer, request_id,
                    error=f"no handler registered for {request_type!r}. known types: {known}",
                )

            payload = request.get("payload") or {}
            if not isinstance(payload, dict):
                return await self._reply(writer, request_id, error="'payload' must be an object")

            try:
                result = await handler(payload)
            except Exception as exc:  # noqa: BLE001 - a handler error must not kill the bridge
                return await self._reply(writer, request_id, error=f"{type(exc).__name__}: {exc}")
            await self._reply(writer, request_id, result=result)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass

    @staticmethod
    async def _reply(
        writer: asyncio.StreamWriter,
        request_id: Any,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if error is not None:
            body: dict[str, Any] = {"id": request_id, "status": "error", "error": error}
        else:
            body = {"id": request_id, "status": "ok", "result": result or {}}
        writer.write(json.dumps(body, ensure_ascii=False, default=str).encode() + b"\n")
        try:
            await writer.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
