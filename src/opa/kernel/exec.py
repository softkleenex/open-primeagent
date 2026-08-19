"""실행 출력 처리 — 이 프로젝트의 핵심 가치가 실제로 구현되는 곳.

원칙: **모델에게 다 주지 않는다.**
  - 응답에는 Config.max_output_chars 까지만 싣는다
  - 전문은 `<session>/outputs/<n>.txt` 에 저장하고 경로만 알려준다
  - 잘랐을 때는 머리/꼬리를 함께 남긴다 (에러 traceback은 꼬리에 있다)
"""

from __future__ import annotations

import re
from pathlib import Path

# IPython traceback은 ANSI 색상코드를 달고 온다. 모델에게는 잡음일 뿐이고
# 컨텍스트만 먹으므로 벗겨서 넘긴다.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)

HEAD_RATIO = 0.6
ELLIPSIS = "\n\n… [{omitted:,} chars omitted — full output: {path}] …\n\n"
ELLIPSIS_NO_PATH = "\n\n… [{omitted:,} chars omitted] …\n\n"


def truncate(text: str, limit: int, *, full_path: Path | None = None) -> tuple[str, bool]:
    """(잘린 텍스트, 잘렸는지) 반환. 머리 60% + 꼬리 40%를 남긴다.

    꼬리를 반드시 남기는 이유: 파이썬 traceback의 실제 원인은 마지막 줄에 있다.
    머리만 남기면 에러 출력이 가장 쓸모없는 형태로 잘린다.
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

    # 마커에 박히는 omitted 숫자가 마커 길이를 바꾸므로 한 번 더 수렴시킨다.
    # (limit을 넘겨서 반환하면 잘라내는 의미가 없다)
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
    """전문을 파일로 남기고 경로를 돌려준다."""
    outputs_dir.mkdir(parents=True, exist_ok=True)
    index = sum(1 for _ in outputs_dir.glob("*.txt"))
    path = outputs_dir / f"{index:05d}.txt"
    path.write_text(text, encoding="utf-8")
    return path
