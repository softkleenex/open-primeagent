"""opa_runtime — 커널 안에서 사는 shim.

원본 `prime-agent-runtime`의 `rlm` 패키지에 대응한다. 차이는 전송 계층뿐:
원본은 Jupyter comm으로 TS 호스트를 부르고, 우리는 Unix socket으로 MCP 서버를 부른다.
API 표면과 request type 이름은 원본과 맞춘다 (원본 문서·스킬 재사용).

커널 부팅 시 이 모듈이 `rlm` / `agent_message` / `harness` 를 노출한다.
(`goal` 은 Phase 4)
"""

from __future__ import annotations

from .client import host_request
from .harness import harness
from .message import agent_message
from .rlm import RLMSpawnHandle, RLMSubagent, rlm

__all__ = [
    "RLMSpawnHandle",
    "RLMSubagent",
    "agent_message",
    "harness",
    "host_request",
    "rlm",
]
