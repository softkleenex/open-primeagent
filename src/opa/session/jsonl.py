"""append-only JSONL 기록/판독. trajectory·turns·mailbox가 전부 이걸 쓴다."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def append(path: Path, record: dict[str, Any]) -> None:
    """한 줄 추가. 부모 디렉터리는 알아서 만든다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, default=str)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()


def read(path: Path, *, since: int = 0, limit: int | None = None) -> Iterator[dict[str, Any]]:
    """깨진 줄은 건너뛴다 — 기록은 유실보다 진행이 우선."""
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


def count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())
