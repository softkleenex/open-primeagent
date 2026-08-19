"""host_request — 커널에서 호스트로 가는 유일한 통로.

    reply = await host_request("rlm.run", {"prompt": ..., "kwargs": {...}})

$OPA_HOST_SOCKET 을 읽는다. child 프로세스도 이 env를 상속받으므로
같은 함수로 부모 호스트를 부를 수 있다 (A2A 양방향의 전제).
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
from typing import Any

ENV_SOCKET = "OPA_HOST_SOCKET"
DEFAULT_TIMEOUT = 300.0

# 호스트(bridge.MAX_LINE_BYTES)와 맞춰야 한다. asyncio 기본값 64KiB를 그대로 두면
# 큰 응답(자식 여러 개의 리포트가 쌓인 inbox)에서 ValueError로 깨진다.
MAX_LINE_BYTES = 8 * 1024 * 1024

_ids = itertools.count(1)


async def host_request(
    request_type: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """호스트에 타입 있는 요청을 보내고 응답을 기다린다.

    호스트가 에러를 반환하거나 해당 타입의 핸들러가 없으면 RuntimeError.
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

    request = {"id": str(next(_ids)), "type": request_type, "payload": payload or {}}

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
            # 핸들러 결과는 result 안에 들어온다 — 프로토콜 키와 절대 충돌하지 않게.
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
