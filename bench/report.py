"""Turn benchmark result files into the markdown table in bench/README.md."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

RESULTS = Path(__file__).parent / "results"
METRICS = [
    ("agent_turns", "turns", "{:.1f}"),
    ("billed_tokens", "billed tokens", "{:,.0f}"),
    ("cost_usd", "cost (USD)", "${:.3f}"),
    ("duration_ms", "wall clock", "{:,.0f} ms"),
]


def summarize(rows: list[dict], key: str) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row[key], []).append(row)
    out = {}
    for name, group in groups.items():
        out[name] = {
            "n": len(group),
            **{
                metric: {
                    "mean": statistics.fmean(r[metric] for r in group),
                    "max": max(r[metric] for r in group),
                }
                for metric, _, _ in METRICS
            },
            "pass_rate": sum(bool(r.get("tests_pass", True)) for r in group) / len(group),
        }
    return out


def table(summary: dict[str, dict], order: list[str]) -> str:
    head = "| metric | " + " | ".join(order) + " | delta |"
    sep = "|---|" + "---|" * (len(order) + 1)
    lines = [head, sep]
    for metric, label, fmt in METRICS:
        values = [summary[name][metric]["mean"] for name in order]
        delta = (values[1] - values[0]) / values[0] * 100 if values[0] else 0.0
        cells = " | ".join(fmt.format(v) for v in values)
        lines.append(f"| {label} | {cells} | {delta:+.0f}% |")
    worst = [summary[name]["agent_turns"]["max"] for name in order]
    lines.append(
        f"| worst-case turns | {worst[0]:.0f} | {worst[1]:.0f} | "
        f"{(worst[1] - worst[0]) / worst[0] * 100:+.0f}% |"
    )
    lines.append("| n | " + " | ".join(str(summary[name]["n"]) for name in order) + " | |")
    return "\n".join(lines)


def main() -> None:
    for variant in ("hard", "easy"):
        evo = RESULTS / f"evolution-{variant}-sonnet.json"
        if not evo.exists():
            continue
        rows = json.loads(evo.read_text(encoding="utf-8"))
        print(f"## Evolution ({variant} variant)\n")
        print(table(summarize(rows, "round"), ["A-no-harness", "B-with-harness"]))
        print()

    warm = RESULTS / "warm-sonnet.json"
    if warm.exists():
        rows = json.loads(warm.read_text(encoding="utf-8"))
        for row in rows:
            row["agent_turns"] = 1
            row["billed_tokens"] = row["child_tokens"]
            row["cost_usd"] = row["child_cost"]
            row["tests_pass"] = row["ok"]
        print("## Sub-agents — warm child vs cold child\n")
        print(table(summarize(rows, "arm"), ["cold", "warm"]))
        print()

    for experiment, order in (("parallel", ["baseline", "opa"]),):
        path = RESULTS / f"subagents-{experiment}-sonnet.json"
        if not path.exists():
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            row["tests_pass"] = True
            row["agent_turns"] = row.get("agent_turns", 0)
            row["billed_tokens"] = row["total_tokens"]
            row["cost_usd"] = row["total_cost"]
        print(f"## Sub-agents — {experiment}\n")
        print(table(summarize(rows, "arm"), order))
        by_arm: dict[str, list[dict]] = {}
        for row in rows:
            by_arm.setdefault(row["arm"], []).append(row)
        parent = " | ".join(
            f"{statistics.fmean(r['parent_tokens'] for r in by_arm[a]):,.0f}" for a in order
        )
        child = " | ".join(
            f"{statistics.fmean(r['child_tokens'] for r in by_arm[a]):,.0f}" for a in order
        )
        print(f"| ├ parent tokens | {parent} | |")
        print(f"| └ child tokens | {child} | |")
        if any("found_count" in r for r in rows):
            found = " | ".join(
                f"{statistics.fmean(r.get('found_count', 0) for r in by_arm[a]):.2f} / 4"
                for a in order
            )
            print(f"| findings | {found} | |")
        print()

    multi = RESULTS / "multiturn-sonnet.json"
    if multi.exists():
        rows = json.loads(multi.read_text(encoding="utf-8"))
        flat = [
            {
                "arm": r["arm"],
                "agent_turns": r["totals"]["agent_turns"],
                "billed_tokens": r["totals"]["billed_tokens"],
                "cost_usd": r["totals"]["cost_usd"],
                "duration_ms": r["totals"]["duration_ms"],
                "tests_pass": r["totals"]["correct"] == 3,
            }
            for r in rows
        ]
        print("## Multi-turn corpus analysis\n")
        print(table(summarize(flat, "arm"), ["baseline", "opa"]))


if __name__ == "__main__":
    main()
