"""host_request — 커널에서 호스트로 가는 유일한 통로.

    reply = await host_request("rlm.run", {"prompt": ..., "kwargs": {...}})

$OPA_HOST_SOCKET 을 읽는다. child 프로세스도 이 env를 상속받으므로
같은 함수로 부모 호스트를 부를 수 있다 (A2A 양방향의 전제).
"""

from __future__ import annotations

import os
from typing import Any

ENV_SOCKET = "OPA_HOST_SOCKET"


async def host_request(request_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """호스트에 타입 있는 요청을 보내고 응답을 기다린다.

    호스트가 에러를 반환하거나 해당 타입의 핸들러가 없으면 RuntimeError.
    """
    if not isinstance(request_type, str) or not request_type:
        raise TypeError("request_type must be a non-empty str")
    if payload is not None and not isinstance(payload, dict):
        raise TypeError(f"payload must be a dict or None, got {type(payload).__name__}")
    if not os.environ.get(ENV_SOCKET):
        raise RuntimeError(
            "open-primeagent host bridge is unavailable "
            f"({ENV_SOCKET} is unset). This kernel was not started by the opa MCP server."
        )
    raise NotImplementedError
