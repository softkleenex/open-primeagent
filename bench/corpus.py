"""Deterministic synthetic corpus, so every benchmark run scores the same task.

Ground truth is computed here rather than by the agent, which is what lets us
mark an answer right or wrong instead of just measuring tokens.
"""

from __future__ import annotations

import random
import shutil
from dataclasses import dataclass
from pathlib import Path

SEED = 20260819
N_FILES = 300
MODULES = ["os", "sys", "json", "re", "math", "pathlib", "typing", "asyncio"]


@dataclass
class GroundTruth:
    files_with_todo: int
    todo_and_os: int
    top3_by_lines: list[str]


def build(root: Path) -> GroundTruth:
    """Write the corpus and return the answers the agent is supposed to find."""
    rng = random.Random(SEED)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    records = []
    for i in range(N_FILES):
        name = f"mod_{i:03d}.py"
        imports = rng.sample(MODULES, rng.randint(1, 4))
        n_todo = rng.choice([0, 0, 0, 1, 1, 2, 3])
        n_lines = rng.randint(20, 200)

        body = [f"import {m}" for m in imports]
        body.append("")
        for line in range(n_lines):
            if n_todo and line % max(1, n_lines // n_todo) == 0 and body.count("# TODO") < n_todo:
                body.append("# TODO")
            body.append(f"def fn_{line}():")
            body.append(f"    return {line}")
        text = "\n".join(body) + "\n"
        (root / name).write_text(text, encoding="utf-8")

        records.append(
            {
                "name": name,
                "todo": text.count("# TODO"),
                "has_os": "import os" in text,
                "lines": text.count("\n"),
            }
        )

    with_todo = [r for r in records if r["todo"] > 0]
    todo_and_os = [r for r in with_todo if r["has_os"]]
    top3 = sorted(todo_and_os, key=lambda r: (-r["lines"], r["name"]))[:3]
    return GroundTruth(
        files_with_todo=len(with_todo),
        todo_and_os=len(todo_and_os),
        top3_by_lines=[r["name"] for r in top3],
    )
