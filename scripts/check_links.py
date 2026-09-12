"""Check every relative markdown link and heading anchor in the repository.

Anchors are not computed here. A hand-rolled slugger is what put three broken
links into this repository in the first place: it stripped `_`, which GitHub
keeps, and it dropped the U+FE0F variation selector, which GitHub keeps. Both
mistakes are invisible in the source.

So the anchors come from GitHub's own rendered HTML (`id="user-content-..."`),
which is the only authority on the question. That means this needs a network
and only checks files already pushed; pass --offline to check file existence
alone.

    uv run python scripts/check_links.py [--offline] [--base <github blob url>]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_BASE = "https://github.com/softkleenex/open-primeagent/blob/main/"
SKIP_DIRS = {"_ref", ".venv", "node_modules", ".git"}
LINK = re.compile(r"\]\((?!https?:|mailto:)([^)#]*)(#[^)]*)?\)")


def markdown_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.md") if not any(part in SKIP_DIRS for part in p.parts)
    )


def rendered_anchors(base: str, relpath: str) -> set[str] | None:
    proc = subprocess.run(
        ["curl", "-sfL", base + relpath], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        return None
    return {"#" + i for i in re.findall(r'id="user-content-([^"]+)"', proc.stdout)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="skip anchor checks")
    parser.add_argument("--base", default=DEFAULT_BASE)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    cache: dict[str, set[str] | None] = {}
    problems: list[str] = []

    for md in markdown_files(root):
        for match in LINK.finditer(md.read_text(encoding="utf-8")):
            path, frag = match.group(1), match.group(2)
            target = (md.parent / path).resolve() if path else md
            here = md.relative_to(root)

            if path and not target.exists():
                problems.append(f"{here}: missing file {path}")
                continue
            if args.offline or not frag or frag == "#":
                continue

            rel = str(target.relative_to(root))
            if rel not in cache:
                cache[rel] = rendered_anchors(args.base, rel)
            anchors = cache[rel]
            if anchors is None:
                problems.append(f"{here}: could not fetch {rel} to check {frag}")
            elif frag not in anchors:
                near = [a for a in anchors if a[:20] == frag[:20]]
                hint = f" (did you mean {near[0]!r}?)" if near else ""
                problems.append(f"{here}: dead anchor {path}{frag}{hint}")

    for line in problems:
        print(line)
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
