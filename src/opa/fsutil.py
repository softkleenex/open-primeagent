"""Writing a file without being able to lose the old one.

`Path.write_text` truncates the file when it opens it. Anything that stops the
write after that - a crash, a killed process, a full disk - leaves the file
empty or half-written, and the previous contents are gone. Measured on this
repository's own projection path: a 2,160-byte `CLAUDE.md` became 0 bytes.

Every durable write here goes through `atomic_write` instead, so a reader only
ever sees a whole file: the old one or the new one.
"""

from __future__ import annotations

import os
from pathlib import Path

SUFFIX = ".opa-tmp"


def atomic_write(target: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write `text` to `target` via a sibling temp file and one rename.

    The temp file is a sibling rather than somewhere under /tmp because
    `os.replace` is only atomic within a filesystem, and a scratch directory is
    routinely on a different one.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Follow symlinks, the way write_text does. os.replace swaps the *name*, so
    # replacing the link itself would leave a regular file where the user had a
    # link - CLAUDE.md -> AGENTS.md is a real setup, and the existing bootstrap
    # test caught this the first time this helper was introduced.
    if target.is_symlink():
        target = target.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + SUFFIX)
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, target)
    except BaseException:
        # Includes KeyboardInterrupt and SystemExit on purpose: an interrupted
        # write should not leave litter next to the file it failed to replace.
        tmp.unlink(missing_ok=True)
        raise
