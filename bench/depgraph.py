"""Does the persistent kernel ever pay for itself? A pre-registered attempt.

Our earlier kernel benchmark (`run.py`) lost by 42% turns, and the write-up
concluded the benchmark was at fault: three questions, each a `grep -c | sort`
one-liner. A shell is already an external computer, so a task solvable by
one-liners gives a persistent kernel nothing to persist.

That diagnosis implies three conditions for the kernel to be worth anything.
This benchmark is built to satisfy all three, and they are stated up front so
that a reader can judge whether the design is fair rather than tuned:

1. **Building the intermediate structure is expensive.** Here it is an import
   graph over 600 modules - not derivable by grep, because reachability and
   longest-path need real traversal.
2. **The questions are adaptive.** Each one names a node that the previous
   answer identified, so they cannot be batched into a single script written
   up front. This is the condition our old benchmark missed most badly.
3. **There are enough turns for a one-off setup cost to amortise.** Eight, not
   three.

PRE-REGISTERED PREDICTION, recorded before the first run:

    (Recorded after the fact, in the commit that fixed the instrumentation:
    the prediction below was written against a token metric that included
    cache writes. See bench/README.md for what the corrected numbers say.)

    The baseline rebuilds the graph every turn - roughly 20 lines of parsing
    re-emitted 8 times - while opa builds it once and then runs one-line
    queries. We expect opa to win on billed tokens, by less than the harness
    benchmark's 22%, and we expect it to lose on wall clock, because a kernel
    round-trip is slower than a subprocess.

    If the baseline instead writes the graph to a JSON file on turn 1 and reads
    it back, it gets the same amortisation through the filesystem and should
    roughly tie. That is a real defeat for the "you need a kernel" claim and
    will be reported as one.

Both arms get identical prompts. Nothing tells either arm how to solve the task,
because an agent decides its own method and a benchmark that dictates one is
measuring its own prompt. Correctness is the check that the work happened: a
three-digit reachability count over a 600-node graph cannot be guessed.

    uv run python bench/depgraph.py --repeat 3
"""

from __future__ import annotations

import argparse
import json
import re
import random
import subprocess
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
N_MODULES = 600
SEED = 20260908


# ---------- corpus ----------

@dataclass
class Truth:
    reachable_from_root: int
    worst_cut: str
    unreachable_if_deleted: int
    longest_path_to_it: int
    closure_of_it: int
    largest_of_those: str
    longest_path_to_that: int
    edges_in_reachable_subgraph: int


def _module_source(index: int, imports: list[int], body_lines: int) -> str:
    lines = [f"# module {index:03d}"]
    lines += [f"import mod_{other:03d}" for other in imports]
    lines += [f"CONST_{index}_{n} = {n}" for n in range(body_lines)]
    lines.append(f"def entry_{index}():")
    lines.append("    return " + (" + ".join(f"mod_{o:03d}.CONST_{o}_0" for o in imports) or "0"))
    return "\n".join(lines) + "\n"


def _reachable(graph: dict[str, list[str]], start: str, skip: str | None = None) -> set[str]:
    seen: set[str] = set()
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for nxt in graph.get(node, ()):
            if nxt == skip or nxt in seen:
                continue
            seen.add(nxt)
            queue.append(nxt)
    seen.discard(skip)
    return seen


def _longest_path(graph: dict[str, list[str]], start: str, target: str) -> int:
    """Edges on the longest start->target path. The graph is a DAG by construction."""
    best: dict[str, int] = {}

    def walk(node: str, depth: int) -> int:
        if node == target:
            return depth
        if node in best and best[node] >= depth:
            return -1
        best[node] = depth
        found = -1
        for nxt in graph.get(node, ()):
            got = walk(nxt, depth + 1)
            found = max(found, got)
        return found

    import sys

    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, N_MODULES * 4))
    try:
        return walk(start, 0)
    finally:
        sys.setrecursionlimit(limit)


def build(root: Path) -> Truth:
    """A tree backbone plus cross edges.

    The backbone matters. An earlier version drew edges to any nearby higher
    index, which produced a wide, shallow graph: closures collapsed to 1,
    deleting any node disconnected only itself, and three of the eight
    questions had constant answers a model could guess without looking.

    A single-parent backbone gives every node a subtree, so "how much would
    deleting this disconnect" is a large and varied number. The extra cross
    edges are what stop that number from simply *being* the subtree size -
    some descendants stay reachable by another route, so the question cannot
    be answered without actually traversing.
    """
    rng = random.Random(SEED)
    root.mkdir(parents=True, exist_ok=True)
    graph: dict[str, list[str]] = {}
    lines_of: dict[str, int] = {}
    edges_out: dict[int, list[int]] = {i: [] for i in range(N_MODULES)}

    # Backbone: six top-level trees, of which root imports three. The other
    # three are orphans, so the reachable count is not simply the file count -
    # an earlier version had every module reachable, which made the first
    # question answerable with `ls | wc -l` and no traversal at all. Cross
    # edges may still reach into an orphan tree, which is the point: what is
    # reachable stops being visible from the directory listing.
    tops = [0, 1, 2, 3, 4, 5]
    for index in range(len(tops), N_MODULES):
        parent = rng.randrange(0, index)
        edges_out[parent].append(index)

    # cross edges, always to a higher index so the result stays acyclic
    for index in range(N_MODULES):
        for _ in range(rng.choice([0, 0, 0, 1, 1, 2])):
            target = rng.randrange(index + 1, N_MODULES) if index + 1 < N_MODULES else None
            if target is not None and target not in edges_out[index]:
                edges_out[index].append(target)

    for index in range(N_MODULES):
        picks = sorted(set(edges_out[index]))
        body = rng.randint(3, 60)
        name = f"mod_{index:03d}.py"
        source = _module_source(index, picks, body)
        (root / name).write_text(source, encoding="utf-8")
        graph[name] = [f"mod_{p:03d}.py" for p in picks]
        lines_of[name] = source.count("\n")

    imported_tops = [0, 2, 4]
    root_source = "\n".join(f"import mod_{t:03d}" for t in imported_tops) + "\n"
    (root / "root.py").write_text(root_source, encoding="utf-8")
    graph["root.py"] = [f"mod_{t:03d}.py" for t in imported_tops]
    lines_of["root.py"] = root_source.count("\n")

    reachable = _reachable(graph, "root.py")

    # Q2: the interior module whose removal disconnects the most.
    #
    # Ranked by in-degree in an earlier version, which always landed on a
    # late near-leaf: cross edges accumulate on high indices, so the biggest
    # hub had a closure of 2 and disconnected nothing.
    #
    # Root's own direct imports are excluded. Each of them is the head of a
    # whole top-level subtree, so one of them always wins, and a model that
    # read root.py could reach the answer by guessing between three names
    # instead of computing anything. Excluding them forces a genuine interior
    # articulation point - and finding it means running reachability once per
    # candidate, which is the shape of work a persistent kernel is supposed to
    # help with.
    direct = set(graph["root.py"])
    candidates = reachable - direct
    damage = {
        n: len((reachable - _reachable(graph, "root.py", skip=n)) | {n}) for n in candidates
    }
    peak = max(damage.values())
    most = min(n for n, c in damage.items() if c == peak)

    closure = len(_reachable(graph, most))
    lost = (reachable - _reachable(graph, "root.py", skip=most)) | {most}

    widest = max(lines_of[n] for n in lost)
    largest = min(n for n in lost if lines_of[n] == widest)

    edges = sum(1 for n in reachable | {"root.py"} for t in graph.get(n, ()) if t in reachable)

    return Truth(
        reachable_from_root=len(reachable),
        worst_cut=most,
        unreachable_if_deleted=len(lost),
        longest_path_to_it=_longest_path(graph, "root.py", most),
        closure_of_it=closure,
        largest_of_those=largest,
        longest_path_to_that=_longest_path(graph, "root.py", largest),
        edges_in_reachable_subgraph=edges,
    )


# ---------- the adaptive chain ----------

PREAMBLE = (
    "This directory holds a Python package where every module imports other "
    "modules by name. Treat `import mod_NNN` as a directed edge. "
)
QUESTIONS = [
    PREAMBLE + "Every question in this session concerns only the modules "
    "reachable from root.py. How many distinct modules are transitively "
    "reachable from root.py by following imports? Do not count root.py "
    "itself. Answer with only the number.",

    "Excluding the modules that root.py imports directly, which single "
    "reachable module would, if deleted, make the greatest number of modules "
    "unreachable from root.py? Some descendants may survive by another route, "
    "so this is not simply the largest subtree. On a tie pick the "
    "lexicographically smallest filename. Answer with only the filename.",

    "Call that module M. Exactly how many modules would become unreachable "
    "from root.py if M were deleted? Count M itself. "
    "Answer with only the number.",

    "What is the length in edges of the longest import path from root.py to "
    "M? Answer with only the number.",

    "How many distinct modules are transitively reachable from M itself? Do "
    "not count M. Answer with only the number.",

    "Among exactly those modules that would become unreachable if M were "
    "deleted, which has the most lines? On a tie pick the lexicographically "
    "smallest filename. Answer with only the filename.",

    "Call that module L. In the original graph, what is the length in edges "
    "of the longest import path from root.py to L? "
    "Answer with only the number.",

    "Finally: counting only modules reachable from root.py plus root.py "
    "itself, how many import edges are there between them? "
    "Answer with only the number.",
]


def expected(truth: Truth) -> list[str]:
    return [
        str(truth.reachable_from_root),
        truth.worst_cut,
        str(truth.unreachable_if_deleted),
        str(truth.longest_path_to_it),
        str(truth.closure_of_it),
        truth.largest_of_those,
        str(truth.longest_path_to_that),
        str(truth.edges_in_reachable_subgraph),
    ]


def _matches(want: str, answer: str) -> bool:
    """Substring matching is not safe here.

    A bare `"362" in answer` also matches the filename `mod_362.py` and the
    number 3620, so an answer could be graded correct for containing a
    coincidence. Require the value as a standalone token instead: not preceded
    by a digit or underscore, not followed by a digit.
    """
    if not want:
        return False
    return re.search(rf"(?<![\d_]){re.escape(want)}(?!\d)", answer) is not None


# ---------- runner ----------

@dataclass
class TurnMetrics:
    """Token fields are kept apart on purpose.

    An earlier version reported one `billed_tokens` = input + output +
    cache_creation. That number made two runs look 20x more expensive than the
    rest when they had in fact done identical work with identical tool calls -
    they were simply the ones that paid to *write* the prompt cache rather than
    read it. Cache writes are an artifact of what else ran on the machine
    recently, not of the task, so a metric that includes them measures the
    wrong thing.

    `work_tokens` (input + output) is what the task cost. `cost_usd` is the
    honest bottom line, since it prices cache reads and writes correctly.
    """

    turn: int
    answer: str
    work_tokens: int
    input_tokens: int
    output_tokens: int
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
            "input_tokens": sum(t.input_tokens for t in self.turns),
            "output_tokens": sum(t.output_tokens for t in self.turns),
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
        proc = subprocess.run(
            cmd, cwd=workspace, capture_output=True, timeout=timeout,
            stdin=subprocess.DEVNULL, check=False,
        )
        elapsed = int((time.monotonic() - started) * 1000)
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = {"result": f"<parse error: {proc.stderr.decode()[:200]}>", "usage": {}}

        usage = payload.get("usage") or {}
        answer = (payload.get("result") or "").strip()
        # Graded against absolute truth, so a wrong answer does not silently
        # excuse the answers that follow it. Where the chain broke is visible
        # in the per-turn record.
        want = answers[index]
        ok = _matches(want, answer)

        tin = int(usage.get("input_tokens", 0))
        tout = int(usage.get("output_tokens", 0))
        metrics.turns.append(
            TurnMetrics(
                turn=index + 1,
                answer=answer[:200],
                work_tokens=tin + tout,
                input_tokens=tin,
                output_tokens=tout,
                cache_write=int(usage.get("cache_creation_input_tokens", 0)),
                cache_read=int(usage.get("cache_read_input_tokens", 0)),
                cost_usd=float(payload.get("total_cost_usd") or 0.0),
                num_turns=int(payload.get("num_turns") or 0),
                duration_ms=elapsed,
                correct=ok,
            )
        )
        mark = "ok " if ok else "MISS"
        t = metrics.turns[-1]
        print(
            f"    turn {index + 1} {mark} want={want!r:14} got={answer[:26]!r:28} "
            f"work={t.work_tokens:>5} cw={t.cache_write:>6} ${t.cost_usd:.4f} ({elapsed}ms)"
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

    base = Path(args.workspace) if args.workspace else REPO / ".bench-depgraph"
    corpus = base / "pkg"
    truth = build(corpus)
    write_mcp_config(corpus)
    print("ground truth:", json.dumps(asdict(truth), indent=2))

    runs: list[RunMetrics] = []
    for cycle in range(args.repeat):
        for arm in args.arms.split(","):
            print(f"\n[{cycle + 1}/{args.repeat}] {arm}")
            runs.append(run_arm(arm, corpus, args.model, args.timeout, truth))
            print("   ", runs[-1].totals)

    out = Path(args.out) / f"depgraph-{args.model}.json"
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
