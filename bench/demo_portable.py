"""Render the cross-agent demo from bench/results/portable-sonnet.json.

Two plain Claude Code sessions on a fresh clone of the same repo, no
open-primeagent attached to either. The only difference: the right one's clone
contains the AGENTS.md that an earlier session (Claude Code + open-primeagent)
wrote after learning the repo's hidden rule. Means of the measured runs; time is
compressed and the frame says so.

    uv run python bench/demo_portable.py --out docs/assets/portable-demo.gif
    uv run python bench/demo_portable.py --out portable-demo.mp4 --width 1280
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from demo import BG, COLD, DIM, FG, FONT, FPS, RULE, WARM, _rect, _text

HERE = Path(__file__).resolve().parent
DATA = HERE / "results" / "portable-sonnet.json"

LENGTH = 15.0
START = 1.5
SLOW_ENDS = 11.0


def means() -> dict:
    rows = json.loads(DATA.read_text(encoding="utf-8"))
    out = {}
    for arm in ("control", "teammate", "learn"):
        runs = [r for r in rows if r["arm"] == arm]
        ok = [r for r in runs if r["tests_pass"]]
        out[arm] = {
            "n": len(runs),
            "passed": len(ok),
            "turns": sum(r["agent_turns"] for r in runs) / len(runs),
            "seconds": sum(r["duration_ms"] for r in runs) / len(runs) / 1000,
            "recorded": sum(1 for r in runs if r.get("block_names_generator")),
        }
    return out


def frame(t: float, d: dict, w: int) -> str:
    k = w / 1280
    m = [f"font '{FONT}'\n", f"affine {k},0,0,{k},0,0\n"]
    add = m.append
    slowest = max(d["control"]["seconds"], d["teammate"]["seconds"])
    scale = (SLOW_ENDS - START) / slowest

    add(
        _text(
            48,
            64,
            "Same repo, fresh clone, plain Claude Code, no open-primeagent",
            size=28,
            fill=FG,
        )
    )
    add(
        _text(
            48,
            100,
            f"replayed from bench/results/portable-sonnet.json - Sonnet, n={d['control']['n']} "
            f"per arm, means - time compressed {1 / scale:.1f}x",
            size=17,
            fill=DIM,
        )
    )
    add(_rect(639, 140, 641, 560, RULE))
    panes = [
        (
            "control",
            48,
            COLD,
            "WITHOUT AGENTS.md",
            [
                "the tests fail: models_gen.py is stale",
                "which of 16 scripts in tools/?",
                "trying them",
            ],
        ),
        (
            "teammate",
            688,
            WARM,
            "WITH THE AGENTS.md AN EARLIER",
            ["AGENTS.md: run tools/sync_models.py", "after editing schema.py", "running it"],
        ),
    ]
    for arm, x, color, label, steps in panes:
        a = d[arm]
        add(_text(x, 170, label, size=22, fill=color))
        if arm == "teammate":
            add(_text(x, 198, "AGENT LEFT IN THE REPO", size=22, fill=color))
        add(_text(x, 240, "task: add a 'phone' field, make the tests pass", size=16, fill=DIM))
        run_for = a["seconds"] * scale
        p = min(1.0, max(0.0, (t - START) / run_for))
        if t >= START:
            step = "done, tests pass" if p >= 1 else steps[min(len(steps) - 1, int(p * len(steps)))]
            add(_text(x, 300, "> " + step, size=18, fill=color if p >= 1 else DIM))
        bar_w = 470
        top = max(d["control"]["turns"], d["teammate"]["turns"])
        turns = a["turns"] * p
        add(_text(x, 370, "agent turns", size=17, fill=DIM))
        add(_rect(x, 382, x + bar_w, 404, RULE))
        if turns > 0:
            add(_rect(x, 382, x + bar_w * turns / top, 404, color))
        add(_text(x + bar_w - 70, 370, f"{turns:4.1f}", size=19, fill=FG))
        real = min(a["seconds"], max(0.0, (t - START) / scale))
        add(_text(x, 460, f"wall clock {real:4.1f}s", size=17, fill=DIM))
        add(_text(x, 500, f"tests passed {a['passed']}/{a['n']}", size=17, fill=DIM))

    if t >= SLOW_ENDS + 0.4:
        c, m_ = d["control"], d["teammate"]
        add(
            _text(
                48,
                612,
                f"{1 - m_['turns'] / c['turns']:.0%} fewer turns, "
                f"{1 - m_['seconds'] / c['seconds']:.0%} less time.",
                size=30,
                fill=FG,
            )
        )
        add(
            _text(
                48,
                656,
                "The rule was learned by Claude Code + open-primeagent and written to AGENTS.md,"
                " which Codex and opencode read too.",
                size=17,
                fill=DIM,
            )
        )
    return "".join(m)


def _magick(mvg_text: str, w: int, h: int, out: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".mvg", delete=False, encoding="utf-8") as fh:
        fh.write(mvg_text)
    try:
        subprocess.run(
            ["magick", "-size", f"{w}x{h}", f"xc:{BG}", "-draw", f"@{fh.name}", str(out)],
            check=True,
        )
    finally:
        Path(fh.name).unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--still", type=float)
    args = parser.parse_args()
    d = means()
    w, h = args.width, args.width * 9 // 16
    if args.still is not None:
        _magick(frame(args.still, d, w), w, h, args.out)
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for i in range(int(LENGTH * FPS)):
            _magick(frame(i / FPS, d, w), w, h, tmpdir / f"f{i:04d}.png")
        frames = ["-framerate", str(FPS), "-i", str(tmpdir / "f%04d.png")]
        base = ["ffmpeg", "-loglevel", "error", "-y", *frames]
        if args.out.suffix == ".gif":
            palette = tmpdir / "palette.png"
            subprocess.run([*base, "-vf", "palettegen=max_colors=32", str(palette)], check=True)
            subprocess.run(
                [*base, "-i", str(palette), "-lavfi", "paletteuse=dither=none", str(args.out)],
                check=True,
            )
        else:
            subprocess.run(
                [*base, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(args.out)], check=True
            )


if __name__ == "__main__":
    main()
