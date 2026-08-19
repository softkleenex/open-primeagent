"""실행 출력 처리 — 이 프로젝트의 핵심 가치가 실제로 구현되는 곳.

원칙: **모델에게 다 주지 않는다.**
  - 응답에는 Config.max_output_chars 까지만 싣는다
  - 전문은 `<session>/outputs/<n>.txt` 에 저장하고 경로만 알려준다
  - 잘랐을 때는 머리/꼬리를 함께 남긴다 (에러 traceback은 꼬리에 있다)
"""

from __future__ import annotations


def truncate(text: str, limit: int) -> tuple[str, bool]:
    """(잘린 텍스트, 잘렸는지) 반환. 머리 60% + 꼬리 40%를 남긴다."""
    raise NotImplementedError
