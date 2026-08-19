"""agent-to-agent messaging.

메일박스는 `<session>/mailbox/<name>.jsonl`. parent의 메일박스 이름은 "parent".

  parent → child : 어댑터 `resume`으로 새 턴을 연다.
                   child는 **이전 컨텍스트를 유지한 채** 이어서 일한다.
                   이것이 "child가 일회용이 아니다"의 실제 구현이다.

  child → parent : 어댑터가 child 최종 출력을 캡처해 parent 메일박스에 적재.
                   (Phase 3에서 child에 opa MCP를 붙이면 작업 도중에도 push 가능)

호스트의 턴 루프를 소유하지 않으므로 수신은 push가 아니라 pull이다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ..session import jsonl

PARENT = "parent"


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Mailbox:
    def __init__(self, mailbox_dir: Path) -> None:
        self.dir = mailbox_dir

    def path(self, name: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name) or "unnamed"
        return self.dir / f"{safe}.jsonl"

    def deliver(self, *, to: str, sender: str, message: str, **extra) -> dict:
        record = {"at": _now(), "sender": sender, "receiver": to, "message": message, **extra}
        jsonl.append(self.path(to), record)
        return record

    def read(self, name: str = PARENT, *, since: int = 0, limit: int | None = None) -> list[dict]:
        return list(jsonl.read(self.path(name), since=since, limit=limit))

    def count(self, name: str = PARENT) -> int:
        return jsonl.count(self.path(name))
