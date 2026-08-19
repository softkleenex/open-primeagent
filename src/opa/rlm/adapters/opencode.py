"""opencode 어댑터 — TODO: headless/resume 인터페이스 조사 필요 (TODO.md 참조).

계약(base.AgentAdapter)만 만족하면 되므로, 세션 재개 방법만 확인되면 붙는다.
"""

from __future__ import annotations

CLI = "opencode"


class OpencodeAdapter:
    name = "opencode"

    def available(self) -> bool:
        raise NotImplementedError
