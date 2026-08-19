"""Refinement helpers - see harness/service.py for the implementation.

Upstream's rules are kept:
  - never modify the base system prompt
  - prefer the smallest possible change
  - keep refinement history and stay reversible

Host slash commands differ per agent, so this ships twice over:
  - portable core: `await harness.apply(...)` from the kernel
  - Claude Code convenience: an `/opa:refine` plugin command
"""

from __future__ import annotations

from pathlib import Path


async def refine(trajectory_path: Path, *, dry_run: bool = False) -> RefineResult:
    raise NotImplementedError


class RefineResult:
    """The proposed delta, whether it was applied, and the rollback event id."""
