"""agent-to-agent messaging.

Mailboxes live at `<session>/mailbox/<name>.jsonl`; the parent's is "parent".

  parent -> child : opens a new turn through the adapter's resume path.
                    The child continues **with its earlier context intact**.
                    This is what "a child is not disposable" means in code.

  child -> parent : the adapter captures the child's final output into the
                    parent mailbox. Attaching the opa MCP server to the child
                    will let it push mid-run as well.

We do not own the host's turn loop, so collection is a pull, not a push.
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
