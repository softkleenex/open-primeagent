"""opencode adapter - TODO: confirm the headless/resume interface (see TODO.md).

Only the base.AgentAdapter contract matters, so once session resume is confirmed
this is a short file.
"""

from __future__ import annotations

CLI = "opencode"


class OpencodeAdapter:
    name = "opencode"

    def available(self) -> bool:
        raise NotImplementedError
