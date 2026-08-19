"""HostBridge — 커널/스킬/child 가 호스트(이 MCP 서버)를 호출하는 통로.

원본은 Jupyter comm(`host.request`)을 쓰지만 우리는 Unix domain socket을 쓴다.
이유는 ARCHITECTURE §2 참조: 커널 재시작과 독립적이고, 커널이 아닌 프로세스
(스킬 서브프로세스, child 에이전트)도 같은 통로를 쓸 수 있다.

프로토콜: 연결당 요청 1개, 한 줄 = JSON 하나.
    →  {"id": "1", "type": "rlm.run", "payload": {...}}
    ←  {"id": "1", "status": "ok",    "result": {...}}
    ←  {"id": "1", "status": "error", "error": "..."}

핸들러 결과를 `result` 안에 **감싼다**. 평탄하게 병합하면 핸들러가 돌려준
`status` 키가 프로토콜의 `status`를 덮어쓴다 (실제로 `rlm.run`의
`status: "running"`이 `status: "ok"`를 덮어써서 클라이언트가 터졌다).
이름 규칙으로 막으면 언젠가 또 깨지므로 구조적으로 불가능하게 한다.

타입 이름은 원본과 동일하게 유지한다 (rlm.run / rlm.list_subagents /
rlm.delete_subagent / rlm.find_models). 원본 문서와 스킬을 그대로 참조하기 위해서.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

# 한 줄의 상한. 커널이 거대한 payload를 밀어넣어 호스트를 죽이지 못하게 한다.
#
# asyncio StreamReader의 기본 limit은 64KiB다. 이걸 안 올리면 64KB 넘는 프롬프트
# (diff를 낀 리뷰 요청)나 64KB 넘는 inbox(자식 여러 개의 리포트)에서 그냥 깨진다.
# 서버·클라이언트 **양쪽** 모두 이 값을 넘겨야 한다.
MAX_LINE_BYTES = 8 * 1024 * 1024


class HostBridge:
    """소켓을 listen 하고 request type 별 핸들러로 디스패치한다."""

    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path
        self._handlers: dict[str, Handler] = {}
        self._server: asyncio.AbstractServer | None = None

    def register(self, request_type: str, handler: Handler) -> None:
        """`rlm.run` 같은 타입에 핸들러를 건다."""
        if request_type in self._handlers:
            raise ValueError(f"handler for {request_type!r} is already registered")
        self._handlers[request_type] = handler

    @property
    def types(self) -> list[str]:
        return sorted(self._handlers)

    async def serve(self) -> None:
        """소켓 수락 루프를 시작한다. 커널보다 먼저 떠 있어야 한다."""
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle, path=str(self.socket_path), limit=MAX_LINE_BYTES
        )
        # 같은 머신의 다른 사용자가 커널에 명령을 밀어넣지 못하게 한다.
        os.chmod(self.socket_path, 0o600)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self.socket_path.exists():
            self.socket_path.unlink()

    # ---------- 내부 ----------

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
            except Exception as exc:  # noqa: BLE001 — 핸들러 예외가 브릿지를 죽이면 안 된다
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
