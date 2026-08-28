"""ToolSurface - rewriting the operating procedure the host model reads, live.

We do not own the system prompt, so the only prompt text we control is our own
tool descriptions. That turns out to be enough: a server can replace a tool's
description and send `notifications/tools/list_changed`, and the host re-reads
the tool list. Measured against Claude Code — the model quoted the new
description verbatim on the **next turn** of the same session
(docs/concepts/evolution.md section 1.2).

So the layers a harness change can reach:

    immediately   the kernel namespace (a new helper is callable at once)
    next turn     this file - the tool description
    next session  projection into CLAUDE.md / AGENTS.md

The description only carries entries **created or changed during this session**.
Older ones were already in the file the host read at startup, so including them
would bill the same text twice.

The channel matters as much as the content, and it took two experiments to get
this right. Announcing behaviour changes through tool *results* gets flagged as
prompt injection, correctly. But so does putting the **rules themselves** in the
description: asked to quote it, Claude Code read our text back verbatim and then
said

    this reads like content injected into a tool description to get me to follow
    an embedded instruction ... I haven't acted on it and won't unless you
    separately ask me to.

It was right. Unattributed imperatives arriving from a server are exactly what a
model should distrust, whichever field they arrive in.

So the description carries an **index, not instructions**: the titles that exist
and how to read them. The imperative text reaches the model through channels
that carry authority - `harness.overview()` when the agent asks for it, and the
project's own CLAUDE.md through projection, which the host presents as the
user's configuration rather than as something we said.

This is the same rule as everywhere else here: context is for deciding, not for
storage.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

logger = logging.getLogger(__name__)

MAX_ENTRIES = 12

HEADER = """

## Notes recorded in this project's harness

Recorded by you or the user via `harness.create`, and not yet written into this
project's CLAUDE.md / AGENTS.md. Listed here so you know they exist -- read the
text with `await harness.overview()` and judge for yourself whether each applies.
"""


def _entry_line(entry: Any) -> str:
    source = str(getattr(entry, "source", "") or "agent")
    recorded = str(getattr(entry, "updated_at", ""))[:10]
    return f"- `{entry.id}` — {entry.title} (recorded by {source}, {recorded})"


class ToolSurface:
    """Owns one tool's description and can rebuild it from harness state."""

    def __init__(self, server: Any, tool_name: str, base_description: str) -> None:
        self.server = server
        self.tool_name = tool_name
        self.base_description = base_description
        self.current_description = base_description
        self._fn: Callable[..., Any] | None = None

    def bind(self, fn: Callable[..., Any]) -> None:
        """Remember the handler so the tool can be re-registered with new text."""
        self._fn = fn

    def render(self, entries: Iterable[Any]) -> str:
        promoted = [e for e in entries if getattr(e, "kind", None) == "prompt"]
        if not promoted:
            return self.base_description
        shown = promoted[:MAX_ENTRIES]
        lines = [self.base_description.rstrip(), HEADER.rstrip(), ""]
        lines += [_entry_line(entry) for entry in shown]
        if len(promoted) > len(shown):
            lines.append(f"- … and {len(promoted) - len(shown)} more; see `harness.overview()`")
        return "\n".join(lines) + "\n"

    async def refresh(self, entries: Iterable[Any], connection: Any = None) -> bool:
        """Rebuild the description and tell the host to re-read the tool list.

        Returns True when the text actually changed. Notifying is best effort:
        a host that ignores `tools/list_changed` still picks the new text up on
        its next `tools/list`, and one that has gone away must not take the
        server down with it.
        """
        new_description = self.render(entries)
        if new_description == self.current_description:
            return False
        if self._fn is None:
            raise RuntimeError("ToolSurface.bind() was never called")

        self.server.remove_tool(self.tool_name)
        self.server.add_tool(self._fn, name=self.tool_name, description=new_description)
        self.current_description = new_description

        if connection is not None:
            try:
                await connection.send_tool_list_changed()
            except Exception as exc:  # noqa: BLE001 - a departed client must not break evolution
                logger.debug("tools/list_changed notification failed: %s", exc)
        return True
