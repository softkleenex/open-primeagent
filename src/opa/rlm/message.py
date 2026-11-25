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

from ..fsutil import atomic_write
from ..session import jsonl

PARENT = "parent"

# A child reaching the parent is a channel a prompt-injected child can also
# reach, so it is bounded. Upstream caps message size, pending count and rate
# for the same reason; without a cap one child can bury everything the others
# said, or blow out the context of whoever reads the mailbox next.
MAX_MESSAGE_CHARS = 16_384
MAX_PENDING_PER_SENDER = 20


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Mailbox:
    def __init__(self, mailbox_dir: Path) -> None:
        self.dir = mailbox_dir

    def path(self, name: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name) or "unnamed"
        return self.dir / f"{safe}.jsonl"

    def deliver(self, *, to: str, sender: str, message: str, **extra) -> dict:
        if len(message) > MAX_MESSAGE_CHARS:
            head = MAX_MESSAGE_CHARS * 3 // 5
            message = (
                message[:head]
                + f"\n… [truncated at {MAX_MESSAGE_CHARS:,} chars] …\n"
                + message[-(MAX_MESSAGE_CHARS - head) :]
            )
        record = {"at": _now(), "sender": sender, "receiver": to, "message": message, **extra}
        jsonl.append(self.path(to), record)
        return record

    # ---- read position ----
    # The mailbox is an append-only log, so "unread" needs a cursor beside it.
    # Without one the per-sender cap counted every message a child had *ever*
    # sent, including the final answer of each turn: after 20 turns a child
    # could never report mid-run again, however often the parent read.

    def _cursor_path(self, name: str) -> Path:
        return self.path(name).with_suffix(".read")

    def cursor(self, name: str = PARENT) -> int:
        try:
            return int(self._cursor_path(name).read_text(encoding="utf-8").strip() or 0)
        except (FileNotFoundError, ValueError):
            return 0

    def _advance(self, name: str, upto: int) -> None:
        if upto > self.cursor(name):
            atomic_write(self._cursor_path(name), str(upto))

    def unread(self, name: str = PARENT) -> list[dict]:
        return self.read(name, since=self.cursor(name))

    def consume(self, name: str = PARENT, *, since: int = 0) -> list[dict]:
        """What `agent_message.inbox` returns; everything returned counts as read."""
        records, end = jsonl.read_to_end(self.path(name), since=since)
        self._advance(name, end)
        return records

    def pending_from(self, sender: str, *, to: str = PARENT) -> int:
        return sum(1 for m in self.unread(to) if m.get("sender") == sender)

    def accepts_from(self, sender: str, *, to: str = PARENT) -> bool:
        """Whether `sender` may add another message, or has said enough unread."""
        return self.pending_from(sender, to=to) < MAX_PENDING_PER_SENDER

    def read(self, name: str = PARENT, *, since: int = 0, limit: int | None = None) -> list[dict]:
        return list(jsonl.read(self.path(name), since=since, limit=limit))

    def count(self, name: str = PARENT) -> int:
        return jsonl.count(self.path(name))
