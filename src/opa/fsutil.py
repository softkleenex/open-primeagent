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
import secrets
import stat
from pathlib import Path

SUFFIX = ".opa-tmp"


def _write_tmp(tmp: Path, text: str, encoding: str) -> None:
    # "x": the name is random, so an existing file means something is wrong.
    # newline="": write the text's own line endings, so a CRLF file stays CRLF.
    with tmp.open("x", encoding=encoding, newline="") as fh:
        fh.write(text)


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

    try:
        st = target.stat()
    except FileNotFoundError:
        st = None

    if st is not None and st.st_nlink > 1:
        # A rename gives the name a new inode and silently splits a hard-linked
        # pair (CLAUDE.md <-> AGENTS.md is a real setup): one name gets the
        # change, the other keeps the stale text forever. Keeping the user's
        # link wins over atomicity here, so write in place.
        with target.open("w", encoding=encoding, newline="") as fh:
            fh.write(text)
        return

    # A unique name, not a fixed `<name>.opa-tmp`: two servers sharing the global
    # harness store write the same target, and with one fixed name each one
    # truncated, renamed away or unlinked the other's temp file.
    tmp = target.with_name(f"{target.name}.{secrets.token_hex(4)}{SUFFIX}")
    try:
        _write_tmp(tmp, text, encoding)
        if st is not None:
            # A new inode starts at the umask default; a 0600 file must not
            # come back 0644.
            os.chmod(tmp, stat.S_IMODE(st.st_mode))
        os.replace(tmp, target)
    except BaseException:
        # Includes KeyboardInterrupt and SystemExit on purpose: an interrupted
        # write should not leave litter next to the file it failed to replace.
        tmp.unlink(missing_ok=True)
        raise
