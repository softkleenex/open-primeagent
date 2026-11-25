"""Append-only JSONL read/write. Trajectory, turns and mailboxes all use this."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def append(path: Path, record: dict[str, Any]) -> None:
    """Append one record, creating the parent directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, default=str)
    with path.open("a+b") as fh:
        # A crash mid-append leaves a last line with no newline. Appending
        # straight after it glued the next record onto the torn one, and the
        # reader then dropped both as one corrupt line.
        fh.seek(0, 2)
        torn = False
        if fh.tell():
            fh.seek(-1, 2)
            torn = fh.read(1) != b"\n"
        fh.write((b"\n" if torn else b"") + line.encode("utf-8") + b"\n")
        fh.flush()


def read(path: Path, *, since: int = 0, limit: int | None = None) -> Iterator[dict[str, Any]]:
    """Skip corrupt lines. One bad record must not block the rest of the log."""
    if not path.exists():
        return
    emitted = 0
    with path.open("r", encoding="utf-8") as fh:
        for index, raw in enumerate(fh):
            if index < since:
                continue
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            yield record
            emitted += 1
            if limit is not None and emitted >= limit:
                return


def read_to_end(path: Path, *, since: int = 0) -> tuple[list[dict[str, Any]], int]:
    """Records from line `since`, and the line index just past the last one read.

    The index comes from the same pass as the records, so a line appended while
    we read can never be counted as read without having been returned.
    """
    if not path.exists():
        return [], since
    records: list[dict[str, Any]] = []
    end = since
    with path.open("r", encoding="utf-8") as fh:
        for index, raw in enumerate(fh):
            if index < since:
                continue
            if not raw.endswith("\n"):
                break  # still being written; leave it for the next read
            end = index + 1
            raw = raw.strip()
            if not raw:
                continue
            try:
                records.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return records, end


def count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())
