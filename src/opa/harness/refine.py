"""refine — trajectory를 보고 harness에 **최소 CRUD delta**를 적용한다.

원본 규칙 유지:
  - base system prompt는 수정하지 않는다
  - 가능한 한 작은 변경만
  - refinement history를 남기고 rollback 가능

호스트 슬래시커맨드는 에이전트마다 다르므로 2중 제공:
  - 이식 가능 코어: 커널에서 `await harness.refine(...)`
  - Claude Code 편의: 플러그인 `/opa:refine`
"""

from __future__ import annotations

from pathlib import Path


async def refine(trajectory_path: Path, *, dry_run: bool = False) -> RefineResult:
    raise NotImplementedError


class RefineResult:
    """제안된 delta + 적용 여부 + rollback용 event id."""
