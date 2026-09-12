"""Does the kernel win when setup is expensive in wall clock rather than tokens?

Benchmarks 0, 0a, 3 and 4 all looked for a token saving from the persistent
kernel and none found one. Benchmark 4 traced why: the baseline rebuilds its
intermediate structure every turn, and that costs nothing, because the rebuild
happens in the shell and only the answer comes back. Tokens are not what
rebuilding costs.

That left one hypothesis standing, stated in bench/README.md as untested: state
that is expensive in *wall clock*. This is the test.

Before building it, the boundary condition was measured directly, because a
filesystem is itself a cache and a shell agent can use it:

    rows        csv    rebuild   pickle w   pickle r   reload/rebuild
     500,000    21 MB     0.4s       0.2s       0.1s        20%
   2,000,000    84 MB     1.6s       1.0s       0.3s        21%
   8,000,000   337 MB     6.2s       5.7s       1.6s        25%

So a baseline that thinks to cache recovers most of the amortisation, and the
kernel's edge is only over a baseline that does not. Over eight turns at 8M
rows the three regimes are roughly: kernel 6s, shell-with-cache 23s, shell
that rebuilds every turn 50s.

PRE-REGISTERED PREDICTION, committed before any run:

    The baseline will rebuild every turn rather than cache, because that is what
    it did in benchmark 4 - it wrote a fresh parsing script each turn without
    ever considering persisting anything. If so, opa wins wall clock by 25-40%
    of total elapsed time and still shows no token difference, because the data
    never enters either arm's context.

    If the baseline does write a pickle on turn 1, the arms should come within
    ~15% and the honest conclusion is that the filesystem is a sufficient cache
    and the kernel's wall-clock advantage is confined to state that cannot be
    serialised at all - a loaded model, an open connection, a GPU context.
    Either way the numbers go in the write-up.

Both arms get identical prompts. Neither is told how to solve anything.

    uv run python bench/bigdata.py --repeat 3
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import random
import re
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
N_ROWS = 8_000_000
SEED = 20260912
N_USERS = 41_237
DAY = 86_400

# Weighted, so the top region wins by a margin rather than by float noise.
# Uniform regions put the answer inside the rounding error of a different
# summation order, which would make the question about arithmetic association
# rather than about the data.
REGIONS = (("apac", 26), ("emea", 21), ("namer", 19), ("latam", 18), ("anz", 16))

# Each action gets its own latency scale so "slowest action" has a real answer,
# and the distribution is skewed because a *uniform* one has no tail: with
# latency uniform on [5, 3000) the mean is 1502 and twice that exceeds the
# maximum, so question 4 counted rows that cannot exist. Caught by the ground
# truth raising before a single agent ran.
ACTION_LATENCY = {
    "view": 3.9, "click": 4.2, "purchase": 5.4,
    "refund": 5.9, "search": 4.6, "share": 4.0,
}
ACTIONS = tuple(ACTION_LATENCY)


@dataclass
class Truth:
    distinct_users: int
    top_region_by_amount: str
    slowest_action_there: str
    slow_events: int
    worst_user: str
    worst_user_amount: int
    worst_user_peak_day: int
    users_above: int


def build(root: Path) -> Truth:
    """Generate the events file and compute every answer with one pass per question."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / "events.csv"
    if not path.exists():
        rng = random.Random(SEED)
        names = [r for r, _ in REGIONS]
        weights = [w for _, w in REGIONS]
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["ts", "user_id", "region", "action", "amount", "latency_ms"])
            for _ in range(N_ROWS):
                action = rng.choice(ACTIONS)
                latency = min(59_999, max(1, int(rng.lognormvariate(ACTION_LATENCY[action], 0.8))))
                writer.writerow(
                    [
                        1735689600 + rng.randrange(30 * DAY),
                        f"u{rng.randrange(N_USERS):05d}",
                        rng.choices(names, weights)[0],
                        action,
                        # An integer, so every sum below is exact. With floats,
                        # two users' totals can land within summation-order
                        # error of each other and "how many are above" stops
                        # having one answer.
                        rng.randrange(1, 50_000),
                        latency,
                    ]
                )

    users: set[str] = set()
    amount_by_region: dict[str, int] = collections.defaultdict(int)
    latency_sum: dict[tuple[str, str], int] = collections.defaultdict(int)
    latency_n: dict[tuple[str, str], int] = collections.defaultdict(int)
    action_lat_sum: dict[str, int] = collections.defaultdict(int)
    action_lat_n: dict[str, int] = collections.defaultdict(int)
    amount_by_user: dict[str, int] = collections.defaultdict(int)

    def scan():
        """Re-read the file instead of holding it.

        Keeping the 8M parsed rows in a list cost a measured 2.4 GB, which put
        the ground truth out of reach of an ordinary laptop before a single
        agent turn ran - for a benchmark whose write-up invites people to copy
        it. Three passes at ~6s each is the better trade.
        """
        with path.open(newline="") as handle:
            reader = csv.reader(handle)
            next(reader)
            for ts, uid, region, action, amount, latency in reader:
                yield int(ts), uid, region, action, int(amount), int(latency)

    for _ts, uid, region, action, amount_i, latency_i in scan():
        users.add(uid)
        amount_by_region[region] += amount_i
        latency_sum[(region, action)] += latency_i
        latency_n[(region, action)] += 1
        action_lat_sum[action] += latency_i
        action_lat_n[action] += 1
        amount_by_user[uid] += amount_i

    peak = max(amount_by_region.values())
    top_region = min(r for r, v in amount_by_region.items() if v == peak)

    means = {
        a: latency_sum[(top_region, a)] / latency_n[(top_region, a)]
        for a in ACTIONS
        if latency_n[(top_region, a)]
    }
    slowest = max(means.values())
    slow_action = min(a for a, v in means.items() if v == slowest)

    overall_mean = action_lat_sum[slow_action] / action_lat_n[slow_action]
    cutoff = 2 * overall_mean

    slow_events = 0
    per_user: dict[str, int] = collections.defaultdict(int)
    for _, uid, _, action, _, latency in scan():
        if action == slow_action and latency > cutoff:
            slow_events += 1
            per_user[uid] += 1

    if not per_user:
        raise AssertionError(
            "no row exceeds twice its action's mean latency - the distribution "
            "has no tail, so questions 4 through 8 have no answers"
        )
    most = max(per_user.values())
    worst_user = min(u for u, c in per_user.items() if c == most)

    worst_amount = amount_by_user[worst_user]
    # "How many distinct days" was the first version and its answer was 30 -
    # the span of the whole file - because the most active user appears on every
    # day of it. Answerable from the header dates alone, without touching the
    # data. The busiest single day is not.
    per_day: dict[int, int] = collections.defaultdict(int)
    for ts, uid, *_ in scan():
        if uid == worst_user:
            per_day[ts // DAY] += 1
    busiest = max(per_day.values())
    peak_day = min(d for d, c in per_day.items() if c == busiest)
    above = sum(1 for v in amount_by_user.values() if v > worst_amount)

    return Truth(
        distinct_users=len(users),
        top_region_by_amount=top_region,
        slowest_action_there=slow_action,
        slow_events=slow_events,
        worst_user=worst_user,
        worst_user_amount=worst_amount,
        worst_user_peak_day=peak_day,
        users_above=above,
    )


PREAMBLE = (
    "This directory holds events.csv with 8 million rows and the header "
    "ts,user_id,region,action,amount,latency_ms. `ts` is a unix timestamp in "
    "seconds. "
)
QUESTIONS = [
    (
        PREAMBLE + "How many distinct user_id values appear in the file? "
        "Answer with only the number."
    ),
    (
        "Which region has the highest total amount summed across all its rows? "
        "On a tie pick the lexicographically smallest. Answer with only the "
        "region name."
    ),
    (
        "Call that region R. Within R only, which action has the highest mean "
        "latency_ms? On a tie pick the lexicographically smallest. Answer with "
        "only the action name."
    ),
    (
        "Call that action A. Across the whole file, compute A's mean latency_ms "
        "over every row with that action. How many rows with action A have "
        "latency_ms strictly greater than twice that mean? "
        "Answer with only the number."
    ),
    (
        "Among the users who have at least one of those rows, which user_id has "
        "the most of them? On a tie pick the lexicographically smallest. "
        "Answer with only the user_id."
    ),
    (
        "Call that user U. What is U's total amount summed over every row in "
        "the file? Answer with only the number."
    ),
    (
        "Treating a day as floor(ts / 86400), on which single day does U have "
        "the most rows? On a tie pick the smallest day number. "
        "Answer with only that day number."
    ),
    (
        "How many distinct users have a strictly higher total amount than U? "
        "Answer with only the number."
    ),
]


def expected(truth: Truth) -> list[str]:
    return [
        str(truth.distinct_users),
        truth.top_region_by_amount,
        truth.slowest_action_there,
        str(truth.slow_events),
        truth.worst_user,
        str(truth.worst_user_amount),
        str(truth.worst_user_peak_day),
        str(truth.users_above),
    ]


def _matches(want: str, answer: str) -> bool:
    if not want:
        return False
    return re.search(rf"(?<![\d_]){re.escape(want)}(?!\d)", answer) is not None


@dataclass
class TurnMetrics:
    turn: int
    answer: str
    work_tokens: int
    cache_write: int
    cache_read: int
    cost_usd: float
    num_turns: int
    duration_ms: int
    correct: bool = False


@dataclass
class RunMetrics:
    arm: str
    model: str
    turns: list[TurnMetrics] = field(default_factory=list)

    @property
    def totals(self) -> dict:
        return {
            "work_tokens": sum(t.work_tokens for t in self.turns),
            "cache_write": sum(t.cache_write for t in self.turns),
            "cache_read": sum(t.cache_read for t in self.turns),
            "cost_usd": round(sum(t.cost_usd for t in self.turns), 4),
            "agent_turns": sum(t.num_turns for t in self.turns),
            "duration_ms": sum(t.duration_ms for t in self.turns),
            "correct": sum(1 for t in self.turns if t.correct),
        }


def write_mcp_config(workspace: Path) -> Path:
    config = {
        "mcpServers": {
            "opa": {
                "command": "uv",
                "args": ["run", "--directory", str(REPO), "opa"],
                "env": {
                    "OPA_WORKSPACE": str(workspace),
                    "OPA_ROOT": str(workspace / ".opa"),
                    "OPA_GLOBAL_ROOT": str(workspace / ".opa-global"),
                },
            }
        }
    }
    path = workspace / "mcp.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def run_arm(arm: str, workspace: Path, model: str, timeout: float, truth: Truth) -> RunMetrics:
    session_id = str(uuid.uuid4())
    answers = expected(truth)
    metrics = RunMetrics(arm=arm, model=model)

    for index, question in enumerate(QUESTIONS):
        cmd = ["claude", "-p", question, "--output-format", "json", "--model", model]
        cmd += ["--session-id", session_id] if index == 0 else ["--resume", session_id]
        if arm == "opa":
            cmd += ["--mcp-config", str(workspace / "mcp.json")]
            cmd += ["--allowedTools", "mcp__opa__opa_python,Bash,Read,Grep,Glob"]
        else:
            cmd += ["--allowedTools", "Bash,Read,Grep,Glob"]

        started = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, cwd=workspace, capture_output=True, timeout=timeout,
                stdin=subprocess.DEVNULL, check=False,
            )
            raw = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired:
            # One slow turn used to abort main() before anything was written,
            # discarding every completed run in the batch - which is an hour of
            # real agent calls thrown away over a single hang.
            raw, stderr = b"", b"<timed out>"
        elapsed = int((time.monotonic() - started) * 1000)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"result": f"<no answer: {stderr.decode()[:200]}>", "usage": {}}

        usage = payload.get("usage") or {}
        answer = (payload.get("result") or "").strip()
        want = answers[index]
        ok = _matches(want, answer)

        metrics.turns.append(
            TurnMetrics(
                turn=index + 1,
                answer=answer[:200],
                work_tokens=int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0)),
                cache_write=int(usage.get("cache_creation_input_tokens", 0)),
                cache_read=int(usage.get("cache_read_input_tokens", 0)),
                cost_usd=float(payload.get("total_cost_usd") or 0.0),
                num_turns=int(payload.get("num_turns") or 0),
                duration_ms=elapsed,
                correct=ok,
            )
        )
        t = metrics.turns[-1]
        print(
            f"    turn {index + 1} {'ok ' if ok else 'MISS'} want={want!r:10} "
            f"got={answer[:24]!r:26} work={t.work_tokens:>5} {elapsed / 1000:>6.1f}s"
        )

    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--arms", default="baseline,opa")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--out", default=str(Path(__file__).parent / "results"))
    parser.add_argument("--workspace", default="")
    args = parser.parse_args()

    base = Path(args.workspace) if args.workspace else REPO / ".bench-bigdata"
    data = base / "data"
    started = time.monotonic()
    truth = build(data)
    print(f"ground truth in {time.monotonic() - started:.0f}s:")
    print(json.dumps(asdict(truth), indent=2))
    write_mcp_config(data)

    runs: list[RunMetrics] = []
    for cycle in range(args.repeat):
        for arm in args.arms.split(","):
            print(f"\n[{cycle + 1}/{args.repeat}] {arm}")
            runs.append(run_arm(arm, data, args.model, args.timeout, truth))
            print("   ", runs[-1].totals)

    out = Path(args.out) / f"bigdata-{args.model}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"truth": asdict(truth), "runs": [asdict(r) | {"totals": r.totals} for r in runs]},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
