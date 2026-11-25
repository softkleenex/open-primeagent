"""Static images for sharing, drawn from the result files, never typed in.

    uv run python bench/charts.py --out docs/assets

writes
    fanout-lost.png      the two fan-out benchmarks, cost and wall clock
    social-preview.png   GitHub's link preview (1280x640; upload it by hand under
                         Settings -> Social preview, the API cannot set it)

Needs ImageMagick (`magick`). Colors were checked with a CVD validator against
the dark surface: blue #4493f8 and red #f85149 stay apart for all three common
color-vision deficiencies, and every bar is labeled too.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from demo import BG, DIM, FG, FONT, RULE, _rect, _text

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
ONE, MANY = "#4493f8", "#f85149"


def _means(name: str, arms: tuple[str, str]) -> dict[str, dict[str, float]]:
    rows = json.loads((RESULTS / name).read_text(encoding="utf-8"))
    out = {}
    for arm in arms:
        runs = [r for r in rows if r["arm"] == arm and r.get("ok", True)]
        out[arm] = {
            "n": len(runs),
            "cost": sum(r["total_cost"] for r in runs) / len(runs),
            "seconds": sum(r["duration_ms"] for r in runs) / len(runs) / 1000,
        }
    return out


def fanout_data() -> list[dict]:
    """Both fan-out benchmarks, as (one agent, four sub-agents) pairs."""
    small = _means("subagents-parallel-sonnet.json", ("baseline", "opa"))
    large = _means("fanout-sonnet.json", ("single", "fanout"))
    return [
        {
            "label": "12-file service",
            "n": small["baseline"]["n"],
            "one": small["baseline"],
            "many": small["opa"],
        },
        {
            "label": "444-file codebase built for fan-out to win",
            "n": large["single"]["n"],
            "one": large["single"],
            "many": large["fanout"],
        },
    ]


def _draw(mvg: str, w: int, h: int, out: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".mvg", delete=False, encoding="utf-8") as fh:
        fh.write(f"font '{FONT}'\n" + mvg)
    try:
        subprocess.run(
            ["magick", "-size", f"{w}x{h}", f"xc:{BG}", "-draw", f"@{fh.name}", str(out)],
            check=True,
        )
    finally:
        Path(fh.name).unlink()


def fanout_chart(out: Path) -> None:
    data = fanout_data()
    w, h = 1200, 675
    m = [
        _text(48, 70, "Fanning out to 4 sub-agents lost. Twice.", size=34, fill=FG),
        _text(
            48,
            108,
            "Sonnet, means. Same findings either way. "
            "Data: bench/results/{subagents-parallel,fanout}-sonnet.json",
            size=15,
            fill=DIM,
        ),
    ]
    # Two panels, each with its own scale: dollars and seconds never share an axis.
    panels = [
        ("cost (USD)", "cost", lambda v: f"${v:.2f}"),
        ("wall clock (seconds)", "seconds", "{:.0f}s".format),
    ]
    bar_max = 320
    for col, (title, key, fmt) in enumerate(panels):
        x0 = 48 + col * 570
        m.append(_text(x0, 170, title, size=20, fill=FG))
        top = max(d["many"][key] for d in data)
        for row, d in enumerate(data):
            y = 215 + row * 200
            m.append(_text(x0, y, f"{d['label']} (n={d['n']})", size=15, fill=DIM))
            for i, (arm, color, name) in enumerate(
                [("one", ONE, "one agent"), ("many", MANY, "4 sub-agents")]
            ):
                by = y + 18 + i * 62
                value = d[arm][key]
                m.append(_rect(x0, by, x0 + max(4, bar_max * value / top), by + 30, color))
                m.append(_text(x0, by + 52, name, size=14, fill=DIM))
                m.append(
                    _text(x0 + bar_max * value / top + 12, by + 22, fmt(value), size=17, fill=FG)
                )
            change = d["many"][key] / d["one"][key] - 1
            m.append(_text(x0 + 420, y + 75, f"+{change:.0%}", size=30, fill=FG))
    m.append(_rect(48, 600, w - 48, 601, RULE))
    m.append(
        _text(
            48,
            636,
            "The single agent grepped a 135k-token codebase using 42k tokens. "
            "Each sub-agent paid ~36k just to start.",
            size=15,
            fill=DIM,
        )
    )
    _draw("".join(m), w, h, out)


def social_preview(out: Path) -> None:
    w, h = 1280, 640
    port = json.loads((RESULTS / "portable-sonnet.json").read_text(encoding="utf-8"))

    def mean(arm: str, key: str) -> float:
        rows = [r[key] for r in port if r["arm"] == arm]
        return sum(rows) / len(rows)

    turns = 1 - mean("teammate", "agent_turns") / mean("control", "agent_turns")
    small = fanout_data()[0]
    fan = small["many"]["cost"] / small["one"]["cost"] - 1
    m = [
        _text(72, 110, "open-primeagent", size=60, fill=FG),
        _text(72, 180, "What one agent learns, the next one reads.", size=32, fill=FG),
        _text(
            72,
            226,
            "Claude Code, Codex, opencode: one AGENTS.md, one MCP server.",
            size=24,
            fill=DIM,
        ),
        _rect(72, 280, w - 72, 281, RULE),
    ]
    stats = [
        (
            f"{turns:.0%} fewer",
            "turns for a fresh agent",
            "using what another learned",
            "#3fb950",
        ),
        (f"{fan:.0%} more", "cost to fan out to", "4 fresh sub-agents (we lost)", MANY),
        ("0 calls", "to our Python kernel", "in 120 turns (we say so)", DIM),
    ]
    for i, (big, line1, line2, color) in enumerate(stats):
        x = 72 + i * 390
        m.append(_text(x, 370, big, size=50, fill=color))
        m.append(_text(x, 415, line1, size=21, fill=FG))
        m.append(_text(x, 445, line2, size=21, fill=FG))
    m.append(_text(72, 560, "claude mcp add opa -- uvx open-primeagent", size=26, fill=FG))
    m.append(_text(72, 598, "github.com/softkleenex/open-primeagent", size=20, fill=DIM))
    _draw("".join(m), w, h, out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True, help="directory")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    fanout_chart(args.out / "fanout-lost.png")
    social_preview(args.out / "social-preview.png")
    for d in fanout_data():
        print(
            d["label"],
            {k: round(v, 3) for k, v in d["one"].items()},
            {k: round(v, 3) for k, v in d["many"].items()},
        )


if __name__ == "__main__":
    main()
