"""append-only JSONL 기록/판독. trajectory·turns·mailbox가 전부 이걸 쓴다."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any


def append(path: Path, record: dict[str, Any]) -> None:
    """한 줄 추가. 부분 쓰기로 파일이 깨지지 않게 원자적으로."""
    raise NotImplementedError


def read(path: Path, *, since: int = 0, limit: int | None = None) -> Iterator[dict[str, Any]]:
    """깨진 줄은 건너뛴다 — 기록은 유실보다 진행이 우선."""
    raise NotImplementedError
