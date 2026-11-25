"""Render the README demo from measured data, not from a staged run.

The animation replays the means of `bench/results/warm-sonnet.json` (n=4): the
same follow-up question asked of a fresh sub-agent and of one that had already
read the code. Nothing on screen is invented; time is compressed, and the frame
says so.

Needs ImageMagick (`magick`) and `ffmpeg`.

    uv run python bench/demo.py --out docs/assets/reuse-demo.gif
    uv run python bench/demo.py --out reuse-demo.mp4 --width 1280
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "results" / "warm-sonnet.json"
FONT = "/System/Library/Fonts/Menlo.ttc"

BG, FG, DIM = "#0d1117", "#e6edf3", "#8b949e"
COLD, WARM, RULE = "#f85149", "#3fb950", "#30363d"

FPS = 15
LENGTH = 15.0  # seconds
START = 1.5  # both runs begin here
COLD_ENDS = 11.0  # the cold arm's real duration is compressed into this


def means() -> dict[str, dict[str, float]]:
    rows = json.loads(DATA.read_text(encoding="utf-8"))
    out = {}
    for arm in ("cold", "warm"):
        runs = [r for r in rows if r["arm"] == arm and r["ok"]]
        out[arm] = {
            "n": len(runs),
            "tokens": sum(r["child_tokens"] for r in runs) / len(runs),
            "cost": sum(r["child_cost"] for r in runs) / len(runs),
            "seconds": sum(r["duration_ms"] for r in runs) / len(runs) / 1000,
        }
    return out


def _text(x: float, y: float, s: str, *, size: float, fill: str) -> str:
    safe = s.replace("\\", "\\\\").replace("'", "\\'")
    return f"fill '{fill}'\nfont-size {size:.1f}\ntext {x:.0f},{y:.0f} '{safe}'\n"


def _rect(x0: float, y0: float, x1: float, y1: float, fill: str) -> str:
    return f"fill '{fill}'\nrectangle {x0:.0f},{y0:.0f} {x1:.0f},{y1:.0f}\n"


def frame(t: float, data: dict, w: int, h: int) -> str:
    """One frame as an MVG drawing. Coordinates are laid out on 1280x720 and scaled."""
    k = w / 1280
    mvg = [f"font '{FONT}'\n", f"affine {k},0,0,{k},0,0\n"]
    add = mvg.append
    scale = (COLD_ENDS - START) / data["cold"]["seconds"]

    add(_text(48, 64, "The same follow-up question, asked two ways", size=30, fill=FG))
    add(
        _text(
            48,
            100,
            f"replayed from bench/results/warm-sonnet.json - Sonnet, n={data['cold']['n']}"
            f" per arm, means - time compressed {1 / scale:.1f}x",
            size=17,
            fill=DIM,
        )
    )
    add(_rect(639, 140, 641, 560, RULE))

    panes = [
        (
            "cold",
            48,
            COLD,
            "A FRESH SUB-AGENT",
            ['rlm("Read api/auth.py. Of the problems', ' in it, which would you fix first?")'],
            ["starting a new session", "reading api/auth.py", "answering"],
        ),
        (
            "warm",
            688,
            WARM,
            "THE SAME ONE, RE-TASKED",
            [
                'agent_message.send("Of the problems in',
                ' api/auth.py, which would you fix first?",',
                ' receiver_name="reviewer")',
            ],
            ["resuming 'reviewer'", "it already read the code", "answering"],
        ),
    ]
    max_tokens = data["cold"]["tokens"]
    max_cost = data["cold"]["cost"]
    for arm, x, color, label, code, steps in panes:
        d = data[arm]
        add(_text(x, 170, label, size=22, fill=color))
        typed = min(1.0, max(0.0, t / START))
        full = "\n".join(code)
        shown = full[: int(len(full) * typed)].split("\n")
        for i, line in enumerate(shown):
            add(_text(x, 212 + i * 26, line, size=17, fill=FG))

        run_for = d["seconds"] * scale
        p = min(1.0, max(0.0, (t - START) / run_for))
        if t >= START:
            step = steps[min(len(steps) - 1, int(p * len(steps)))] if p < 1 else "done"
            add(
                _text(
                    x,
                    310,
                    ("> " + step) if p < 1 else "> done",
                    size=18,
                    fill=DIM if p < 1 else color,
                )
            )

        bar_w = 470
        for row, (name, value, top, fmt) in enumerate(
            [
                ("tokens", d["tokens"] * p, max_tokens, lambda v: f"{v:,.0f}"),
                ("cost", d["cost"] * p, max_cost, lambda v: f"${v:.3f}"),
            ]
        ):
            y = 370 + row * 70
            add(_text(x, y, name, size=17, fill=DIM))
            add(_rect(x, y + 12, x + bar_w, y + 34, RULE))
            if value > 0:
                add(_rect(x, y + 12, x + bar_w * value / top, y + 34, color))
            add(_text(x + bar_w - 130, y, fmt(value), size=19, fill=FG))
        real = min(d["seconds"], max(0.0, (t - START) / scale))
        add(_text(x, 530, f"wall clock {real:4.1f}s", size=17, fill=DIM))

    done_at = COLD_ENDS + 0.4
    if t >= done_at:
        cost_cut = 1 - data["warm"]["cost"] / data["cold"]["cost"]
        token_cut = 1 - data["warm"]["tokens"] / data["cold"]["tokens"]
        add(
            _text(
                48,
                620,
                f"{cost_cut:.0%} less cost, {token_cut:.0%} fewer tokens.",
                size=30,
                fill=FG,
            )
        )
        add(
            _text(
                48,
                664,
                "open-primeagent keeps the sub-agent, so the follow-up does not "
                "pay for reading the code again.",
                size=19,
                fill=DIM,
            )
        )
    return "".join(mvg)


def render(out: Path, width: int) -> None:
    for tool in ("magick", "ffmpeg"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} is required")
    data = means()
    height = width * 9 // 16
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for i in range(int(LENGTH * FPS)):
            mvg = tmpdir / f"f{i:04d}.mvg"
            mvg.write_text(frame(i / FPS, data, width, height), encoding="utf-8")
            subprocess.run(
                [
                    "magick",
                    "-size",
                    f"{width}x{height}",
                    f"xc:{BG}",
                    "-draw",
                    f"@{mvg}",
                    str(tmpdir / f"f{i:04d}.png"),
                ],
                check=True,
            )
        frames = ["-framerate", str(FPS), "-i", str(tmpdir / "f%04d.png")]
        if out.suffix == ".gif":
            palette = tmpdir / "palette.png"
            subprocess.run(
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-y",
                    *frames,
                    "-vf",
                    "palettegen=max_colors=32",
                    str(palette),
                ],
                check=True,
            )
            subprocess.run(
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-y",
                    *frames,
                    "-i",
                    str(palette),
                    "-lavfi",
                    "paletteuse=dither=none",
                    str(out),
                ],
                check=True,
            )
        else:
            subprocess.run(
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-y",
                    *frames,
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(out),
                ],
                check=True,
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--still", type=float, help="render one frame at this second, as PNG")
    args = parser.parse_args()
    if args.still is not None:
        data = means()
        h = args.width * 9 // 16
        with tempfile.NamedTemporaryFile("w", suffix=".mvg", delete=False) as fh:
            fh.write(frame(args.still, data, args.width, h))
        subprocess.run(
            [
                "magick",
                "-size",
                f"{args.width}x{h}",
                f"xc:{BG}",
                "-draw",
                f"@{fh.name}",
                str(args.out),
            ],
            check=True,
        )
        Path(fh.name).unlink()
        return
    args.out.parent.mkdir(parents=True, exist_ok=True)
    render(args.out, args.width)


if __name__ == "__main__":
    main()
