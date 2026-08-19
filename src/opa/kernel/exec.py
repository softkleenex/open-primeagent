"""Execution output handling - where this project's core claim is implemented.

The rule: **do not hand the model everything.**
  - the reply carries at most Config.max_output_chars
  - the full text goes to `<session>/outputs/<n>.txt` and we return the path
  - a truncated view keeps head *and* tail (a traceback's cause is at the tail)
"""

from __future__ import annotations

import re
from pathlib import Path

# IPython tracebacks arrive wrapped in ANSI colour codes. To the model that is
# noise that only burns context, so strip it before handing it over.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)

HEAD_RATIO = 0.6
ELLIPSIS = "\n\n… [{omitted:,} chars omitted — full output: {path}] …\n\n"
ELLIPSIS_NO_PATH = "\n\n… [{omitted:,} chars omitted] …\n\n"


def truncate(text: str, limit: int, *, full_path: Path | None = None) -> tuple[str, bool]:
    """Return (text, was_truncated). Keeps 60% head and 40% tail.

    The tail is non-negotiable: the real cause of a Python traceback is on the
    last line, so a head-only cut is the least useful cut possible.
    """
    if limit <= 0 or len(text) <= limit:
        return text, False

    marker = (
        ELLIPSIS.format(omitted=0, path=full_path)
        if full_path is not None
        else ELLIPSIS_NO_PATH.format(omitted=0)
    )
    budget = limit - len(marker)
    if budget <= 0:
        return text[:limit], True

    # The omitted-count printed in the marker changes the marker length, so
    # converge once more. Returning more than `limit` would defeat the purpose.
    head_len = tail_len = 0
    for _ in range(3):
        head_len = int(budget * HEAD_RATIO)
        tail_len = budget - head_len
        omitted = len(text) - head_len - tail_len
        marker = (
            ELLIPSIS.format(omitted=omitted, path=full_path)
            if full_path is not None
            else ELLIPSIS_NO_PATH.format(omitted=omitted)
        )
        new_budget = limit - len(marker)
        if new_budget == budget:
            break
        budget = new_budget
        if budget <= 0:
            return text[:limit], True

    return text[:head_len] + marker + text[-tail_len:], True


def store_full(outputs_dir: Path, text: str) -> Path:
    """Write the full text to a file and return its path."""
    outputs_dir.mkdir(parents=True, exist_ok=True)
    index = sum(1 for _ in outputs_dir.glob("*.txt"))
    path = outputs_dir / f"{index:05d}.txt"
    path.write_text(text, encoding="utf-8")
    return path
