"""MCP 서버 엔트리포인트.

노출 도구는 의도적으로 4개뿐이다 (ARCHITECTURE §3):
    opa_python / opa_status / opa_kernel / opa_bootstrap

rlm·harness·goal·agent_message는 도구가 아니라 커널 안의 Python 심볼이다.
호스트 에이전트의 도구 목록을 오염시키지 않는 것이 이 프로젝트의 전제다.
"""

from __future__ import annotations


def main() -> None:
    """stdio MCP 서버를 띄운다. `opa` 콘솔 스크립트의 진입점."""
    raise NotImplementedError("Phase 0: MCP handshake 구현 예정 (ROADMAP Phase 0 Exit)")


if __name__ == "__main__":
    main()
