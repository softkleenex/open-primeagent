"""How expensive must state be before a persistent kernel could show up at all?

Six benchmarks looked for a kernel effect and found none. This answers the
remaining question arithmetically instead of by building a seventh and choosing
its scale until one appeared, which is the mistake benchmark 4 already records.

Two measurements decide it, and both are taken here rather than assumed:

  1. what a rebuild costs, against what a turn of model time costs
  2. whether writing the state to disk makes the rebuild cheaper

The second is the one people skip. A filesystem is a cache, and for anything
picklable it is a good one - which is why most "expensive state" never reaches
the kernel's regime at all.

    uv run python bench/threshold.py
"""

from __future__ import annotations

import pickle
import random
import re
import subprocess
import sys
import time

# Median turn across benchmarks 4 and 5, both on this machine.
TURN_SECONDS = 15.0
# Observed run-to-run spread in those benchmarks. Below this, nothing is visible.
NOISE = 0.20


def _time_process(code: str, runs: int = 3) -> float:
    best = None
    for _ in range(runs):
        started = time.monotonic()
        subprocess.run([sys.executable, "-c", code], capture_output=True, check=True)
        elapsed = time.monotonic() - started
        best = elapsed if best is None else min(best, elapsed)
    return best or 0.0


def _patterns(n: int) -> list[str]:
    rng = random.Random(11)
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    return [
        rf"(?i)\b{rng.choice(words)}[-_]?"
        + "".join(rng.choice("abcdefghij") for _ in range(rng.randint(3, 9)))
        + r"\d{0,3}\b"
        for _ in range(n)
    ]


def main() -> None:
    print("Part 1 - what fraction of a run could a kernel save?\n")
    print(f"  {'rebuild':>9}  " + "  ".join(f"{n:>5} turns" for n in (3, 8, 20)))
    for rebuild in (0.02, 0.5, 1.0, 2.0, 3.5, 6.0, 12.0, 30.0):
        cells = [
            f"{(n - 1) * rebuild / (n * TURN_SECONDS + rebuild):>10.1%}" for n in (3, 8, 20)
        ]
        print(f"  {rebuild:>8.2f}s  " + "  ".join(cells))
    print(f"\n  Run-to-run spread is about {NOISE:.0%}, so a rebuild under roughly")
    print("  two seconds cannot be distinguished from noise at any turn count.\n")

    print("Part 2 - does writing it to disk make the rebuild cheaper?\n")
    print("  (if it does, a shell amortises through the filesystem and needs no kernel)\n")

    start = _time_process("pass")
    print(f"  {'interpreter start':<34} {start * 1000:7.0f} ms - a shell pays this per turn")

    for n in (20_000, 150_000):
        pats = _patterns(n)
        t0 = time.monotonic()
        compiled = [re.compile(p) for p in pats]
        build = time.monotonic() - t0
        blob = pickle.dumps(compiled)
        t0 = time.monotonic()
        pickle.loads(blob)
        reload_ = time.monotonic() - t0
        print(
            f"  {f'compile {n:,} regexes':<34} build {build:5.2f}s  "
            f"reload {reload_:5.2f}s  ({reload_ / build:.0%} of build)"
        )

    print("\n  Compiled patterns do not serialise: pickle stores the source and")
    print("  recompiles, so the filesystem returns nothing. A parsed data structure")
    print("  does - benchmark 5 measured a reload at 25% of rebuild across three")
    print("  orders of magnitude.\n")
    print("  The kernel's regime is the intersection: more than ~2s to rebuild, and")
    print("  nothing to gain from disk. Loaded models, live connections, GPU")
    print("  contexts. Not parsed files, not indexes, not anything picklable.")


if __name__ == "__main__":
    main()
