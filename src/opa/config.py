"""환경 변수 기반 설정. 호스트 에이전트를 바꾸지 않는다는 제약상,
설정은 전부 MCP 서버 등록 줄의 env로만 들어온다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# 커널·child가 호스트를 호출할 때 쓰는 소켓 경로 (자식 프로세스에 상속)
ENV_HOST_SOCKET = "OPA_HOST_SOCKET"
ENV_SESSION_DIR = "OPA_SESSION_DIR"
ENV_ROLE = "OPA_ROLE"  # "parent" | "child"


@dataclass(frozen=True)
class Config:
    root: Path                 # opa 상태 루트 (기본 <cwd>/.opa)
    workspace: Path            # 호스트 에이전트의 작업 디렉터리
    max_output_chars: int      # opa_python 응답에 실을 최대 문자 수
    default_adapter: str       # "claude-code" | "codex" | ...
    child_permission_mode: str # 보수적 기본값. bypass는 명시적 opt-in만.
    allow_dangerous_child: bool

    @classmethod
    def from_env(cls) -> Config:
        workspace = Path(os.environ.get("OPA_WORKSPACE", os.getcwd())).resolve()
        return cls(
            root=Path(os.environ.get("OPA_ROOT", workspace / ".opa")).resolve(),
            workspace=workspace,
            max_output_chars=int(os.environ.get("OPA_MAX_OUTPUT_CHARS", "4000")),
            default_adapter=os.environ.get("OPA_DEFAULT_ADAPTER", "claude-code"),
            child_permission_mode=os.environ.get("OPA_CHILD_PERMISSION_MODE", "acceptEdits"),
            allow_dangerous_child=os.environ.get("OPA_ALLOW_DANGEROUS_CHILD") == "1",
        )
