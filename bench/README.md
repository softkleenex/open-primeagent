# Benchmarks

Measured, not argued. Every number below came from running `claude -p
--output-format json` and reading the `usage` and `total_cost_usd` fields it
reports. Raw results are in [`results/`](results/), and the scripts that produced
them are in this directory.

**Two of the three benchmarks say open-primeagent made things worse.** They are
kept here on purpose: they are what makes the third one worth believing, and
they say something more useful than a win would.

```
uv run python bench/evolution.py --variant hard --repeat 7
uv run python bench/evolution.py --variant easy --repeat 3
uv run python bench/run.py --repeat 3
uv run python bench/report.py
```

All runs: Sonnet, macOS, one machine, sequential. `billed tokens` =
`input + output + cache_creation` (cache reads are reported separately in the
raw JSON and excluded here, since they are billed at a fraction of the rate).

**The cost column is an API-rate equivalent, not a charge.** These runs used a
subscription login, where consumption counts against rate limits rather than
being billed per token. `total_cost_usd` is what Claude Code computes the same
usage would cost at API rates, and it is reported here because it is a single
comparable number — not because anyone was invoiced for it. Tokens are the
figure to compare.

```
uv run python bench/subagents.py --experiment parallel --repeat 3
uv run python bench/fanout.py --repeat 2
uv run python bench/serial.py --repeat 3 --seconds 30
uv run python bench/warm.py --repeat 4
```

---

## 0. Sub-agent fan-out  ❌ opa loses badly

`bench/subagents.py --experiment parallel`

A 12-file service with one planted defect per review dimension (a hardcoded
credential and SQL concatenation, an untested module, a quadratic scan, three
different error response shapes). Both arms are asked for the most important
concrete finding in each of the four dimensions.

- **baseline** — plain Claude Code, with its own `Task` tool available
- **opa** — spawns one named sub-agent per dimension via `rlm()`, polls the
  mailbox, and summarises

**Child tokens are counted.** The parent's `usage` reports only the parent, so
reading it alone would make opa look nearly free. Every child's tokens and cost
come from the registry and are added in.

| metric | baseline | opa | delta |
|---|---|---|---|
| turns | 13.7 | 14.3 | +5% |
| billed tokens | 34,286 | 189,858 | **+454%** |
| cost (USD) | $0.287 | $2.522 | **+777%** |
| wall clock | 35,169 ms | 121,114 ms | **+244%** |
| ├ parent tokens | 34,286 | 45,251 | |
| └ child tokens | 0 | 144,607 | |
| findings | 3.33 / 4 | 3.00 / 4 | |
| n | 3 | 3 | |

Same findings. Nearly nine times the cost.

**The mechanism is a fixed startup cost per child.** 144,607 child tokens across
four children is roughly **36k tokens each, before a child does any work** —
that is a full Claude Code session paying for its system prompt and tool
schemas. Reviewing the entire 12-file project cost the baseline 34k tokens in
total. *Spawning one child cost more than doing the whole job.*

So the rule fan-out has to clear:

> A sub-agent pays only when the work you hand it would cost the parent more
> than ~36k tokens of its own context.

On a small codebase that is never true, and no amount of parallelism fixes it —
the wall clock got worse too, because four cold sessions have to boot.

We have not yet measured the case where it should win: a codebase large enough
that the parent could not hold the material at all. Until we do, **there is no
measured evidence that sub-agent fan-out is worth it**, and
[the docs say so where people will read them](../docs/concepts/rlm.md#when-not-to-fan-out).

## 0-. Ownership and verification  ⚠ the finding was not the one we went looking for

`bench/serial.py`, `bench/slowsuite.py`

Four subsystems, one small planted bug each, and an acceptance check per
subsystem that blocks for 30s before it can report — the shape of a build. Both
arms are told to fix all four, run every check, and report each one's output.

- **single** — one agent does all four
- **fanout** — one child per subsystem

The question was whether serial blocking work finally makes fan-out worth it.
The answer turned out to be about something else.

| | single | fanout |
|---|---|---|
| subsystems fixed | 4/4, 4/4, 4/4 | 4/4, 4/4, 4/4 |
| **checks actually run** | **4/4, 0/4, 0/4** | **4/4, 4/4, 4/4** |
| wall clock | 93s, 51s, 55s | 66s, 53s, 51s |
| billed tokens | 43,135 | 119,449 |
| checks tampered with | 0 | 0 |
| n | 3 | 3 |

**Four specialists each verified their own subsystem, every time. One agent
doing all four verified everything once in three runs** — the other two times it
fixed the code correctly by inspection and never ran a check, despite being told
to run all four and report their output.

Nobody edited an acceptance check, in any run of any arm.

That makes the wall-clock column mostly unusable: two of the three single runs
are fast because they skipped work. On the one occasion both arms did the same
thing, single took **93s against fan-out's 56s** — n=1, directional at best.

What is measured, at n=3 on both sides, is the verification behaviour. A
plausible reading is that ownership does it: a child that owns one subsystem
runs its one check, while an agent holding four decides three of them are
obvious. We have not tested that explanation.

Fan-out still costs **2.8x the tokens**, for the same fixes.

### It took four attempts to measure anything

Worth recording, because the failures were all the same shape.

1. Children could not run shell commands at all. `--permission-mode acceptEdits`
   alone leaves a headless child asking for an approval nobody is there to give;
   it could edit files but never test them. Fixed in the product, not the
   benchmark — see [rlm.md](../docs/concepts/rlm.md#a-child-needs-tools-not-just-permission).
   Results archived as `results/serial-INVALID-children-could-not-run-commands.json`.
2. With that fixed, the task said "make the checks pass", so an agent could fix
   by inspection and skip the blocking work entirely. The prompt was tightened.
3. The tightened prompt did not bind either — runs still finished well under the
   120s of mandatory sleep. Archived as `results/serial-unequal-verification.json`.
4. Each check now writes a receipt before it can fail, so grading can report what
   was actually run rather than what was asked for.

The lesson generalises: **an agent decides how much verification to do, so a
benchmark cannot impose work through its prompt.** If the scoring cannot tell
whether the work happened, the numbers are measuring something else. All three
earlier versions produced plausible tables.

## 0a. Fan-out on a large codebase  ❌ it loses even here

`bench/fanout.py`

Benchmark 0 was open to two fair objections: the project was trivial, and every
child re-read all of it. This one removes both. **444 files, ~135k tokens, four
independently ownable subsystems** (auth, billing, catalog, delivery), each
carrying exactly one planted defect, and each child scoped to one subsystem so
nothing is read twice.

**What this can even show.** With children scoped, the reading is identical
either way, so fan-out spends three extra session startups (~108k tokens) *by
construction*. It cannot win on total tokens and we do not pretend to test that.
The two hypotheses that could hold are:

- **H1** fan-out is faster, because independent subsystems run at once
- **H2** fan-out finds more, because each child holds one subsystem instead of four

| metric | single | fanout | delta |
|---|---|---|---|
| billed tokens | 41,985 | 150,821 | +259% |
| cost (USD) | $0.240 | $1.011 | +320% |
| wall clock | 49.6 s | 112.8 s | **+127%** |
| defects found | 2.5 / 4 | 3.0 / 4 | |
| n | 2 | 2 | |

**H1 fails.** Four children running concurrently were still **2.3x slower** than
one agent working alone.

**H2 is not established.** 3.0 against 2.5 at n=2 is noise. It may be real; this
does not show it.

### Why parallelism did not help

Look at what the single agent actually spent: **42k tokens on a 135k-token
codebase**. It never read the repository. It grepped, opened four or five files,
and answered.

That is the whole result. Fan-out is supposed to relieve a bottleneck — one
context having to hold everything — and **a competent agent never creates that
bottleneck**, because it searches instead of reading. Meanwhile each child still
pays ~36k tokens and ~30 seconds of session startup before it can grep anything,
and the wall clock is set by the slowest child plus the parent's coordination
turns.

Making the codebase bigger does not change this. It makes the single agent grep
a little more and adds nothing to the children's fixed cost.

**So we now have no measured case where sub-agent fan-out wins** — not on a small
project, not on a large one, not on tokens, cost, or wall clock. If there is one,
it is somewhere we have not looked, and the burden is on the next benchmark.

## 0b. Warm child vs cold child  ✅ reuse wins by 5x

`bench/warm.py`

A sub-agent has already read `api/auth.py` and reported on it. Now it gets a
follow-up: *which problem would you fix first, and what would the fixed code
look like?*

- **cold** — a new `rlm()` child that must read the file itself
- **warm** — `agent_message.send` to the child that already read it

Only the follow-up turn is measured; both arms pay for the same setup child.

| metric | cold | warm | delta |
|---|---|---|---|
| billed tokens | 23,058 | 1,987 | **-91%** |
| cost (USD) | $0.176 | $0.034 | **-81%** |
| wall clock | 21,551 ms | 13,282 ms | **-38%** |
| n | 4 | 4 | |

Variance is tiny — every cold run landed near 23k tokens and every warm run near
2k.

**The first version of this benchmark was invalid, and it is worth saying why.**
It drove both arms through `claude -p` and asked the host agent to re-task the
existing sub-agent. Instrumenting `child_turns` showed that on 2 of 3 runs the
child never ran at all: the parent answered from the report already sitting in
its own context. The experiment was measuring the parent's discretion, not warm
versus cold. Those results are kept in
`results/subagents-warm-INVALID-host-driven.json`.

The rewrite removes the host agent entirely and drives the opa server in-process
with a fixed snippet, and asserts `turns` advanced by exactly one on the child
being measured. Every run in the table above passed that check.

### What 0 and 0b are together

They are the same fact seen from both sides:

> A child costs roughly **36k tokens of session startup**. Spawning is
> expensive; keeping one is nearly free.

**That 36k is our architecture's price, not sub-agents'.** Upstream Prime Agent
spawns a child as another session inside its own process, inheriting the
runtime; it never pays a cold CLI boot. We shell out to the user's own
`claude` / `codex` precisely so we do not have to own the host — and this is
the bill for that choice. Anyone reading these numbers as "sub-agent fan-out
does not work" is reading them too broadly; what they show is that **fan-out
does not survive a per-child process boot**.

Fanning out to four fresh specialists cost 8.8x. Re-tasking one that was already
warm cost **one fifth** as much in dollars, on **one twelfth** the tokens. So the value in sub-agents is not
parallelism — it is that **the child persists**, which is exactly what the
registry exists for and what "a child is not disposable" was always supposed to
mean.

> [!note]
> **These three tables report `billed tokens` = input + output + cache writes**,
> the metric [benchmark 5](#5-large-file-adaptive-chain---the-agent-never-used-the-kernel--in-either-benchmark)
> shows is partly an artifact of what else ran on the machine recently. The
> `work tokens` rows were recomputed from the same raw files afterwards and are
> the honest figure. The correction runs in both directions: it makes the
> harness look considerably better (-22% becomes -64%) and makes opa look
> considerably worse on benchmark 3 (+16% becomes +249%). Both are published.
>
> Benchmarks 1-3 report **means**; benchmarks 4 and 5 report **medians** with
> ranges, which is the better practice and the one to copy.

## 1. Evolution — hard variant  ✅ the harness pays

`bench/evolution.py --variant hard`

A project with a rule you cannot infer from the code you are asked to touch:
editing `schema.py` requires re-running a generator, or the test suite fails
against a stale generated module. The generator is one of **16 scripts under
`tools/`**, the failure message does not name it, and fifteen decoys
(`make_models.py`, `regen_types.py`, `sync_schema.py`, …) look equally
plausible.

- **A** — no harness. The agent has to discover the rule by failing.
- **B** — one harness entry naming the generator, projected into `CLAUDE.md`.

Identical task, identical freshly generated workspace. The only difference is
the projected harness.

| metric | A: no harness | B: with harness | delta |
|---|---|---|---|
| turns | 15.6 | 10.3 | **-34%** |
| billed tokens | 25,278 | 19,693 | **-22%** |
| work tokens (input+output) | 3,655 | 1,303 | **-64%** |
| cost (USD) | $0.355 | $0.232 | **-35%** |
| wall clock | 58,171 ms | 25,280 ms | **-57%** |
| worst-case turns | 24 | 11 | **-54%** |
| n | 7 | 7 | |

Both arms passed the tests every time, so this is efficiency, not correctness.

The mean understates it. Without the harness the run is *unpredictable* — the
worst attempt took 24 turns and 145 seconds hunting through `tools/`, while the
best took 12. With the harness every attempt landed between 9 and 11 turns.
**Variance collapsed**, which in practice matters more than the mean.

## 2. Evolution — easy variant  ❌ the harness costs you

`bench/evolution.py --variant easy`

Same task, except `generate.py` sits in the project root next to `schema.py`.
Rediscovering the rule now takes one glance.

| metric | A: no harness | B: with harness | delta |
|---|---|---|---|
| turns | 9.0 | 11.3 | +26% |
| billed tokens | 18,611 | 19,234 | +3% |
| work tokens (input+output) | 1,084 | 1,171 | +8% |
| cost (USD) | $0.206 | $0.232 | +13% |
| n | 3 | 3 | |

The harness entry is pure overhead here. Sonnet finds `generate.py` immediately,
so there is nothing to save, and the `CLAUDE.md` block still has to be read.

**Together, 1 and 2 are the actual finding**: a harness entry pays for itself
exactly in proportion to how expensive the knowledge is to rediscover. Promoting
a fact the model can re-derive in one glance makes things worse. This is the
empirical case for the rule that only *repeated* signals are promotion
candidates.

## 3. Multi-turn corpus analysis  ❌ opa loses

`bench/run.py`

300 generated Python files. Three dependent turns in one session: count files
with a `# TODO`, then how many of *those* also `import os`, then which three of
*those* have the most lines. Baseline gets Bash/Read/Grep/Glob; the opa arm gets
the same plus `opa_python` and the one-line guidance the product's own
projection writes.

| metric | baseline | opa | delta |
|---|---|---|---|
| turns | 6.3 | 9.0 | +42% |
| billed tokens | 17,312 | 20,008 | +16% |
| work tokens (input+output) | 440 | 1,346 | **+206%** |
| cost (USD) | $0.183 | $0.243 | +33% |
| wall clock | 22,504 ms | 37,094 ms | +65% |
| n | 3 | 3 | |

Both arms answered all three turns correctly every time.

**Why it lost, and why the benchmark is the thing at fault**: this task is a
`grep -c | sort` one-liner. A shell *is already an external computer*, so the
persistent kernel had nothing to persist that mattered, and the MCP server added
tool-schema tokens and extra round trips on top.

The hypothesis "keeping intermediate state in Python saves context" needs a task
where the intermediate state is expensive to rebuild **and** cannot be re-derived
by a one-liner. This one is neither. We have not yet built that benchmark, so
**there is currently no measured evidence that the persistent kernel saves
tokens**, and the README does not claim there is.

---

## 4. Import graph, adaptive chain  ❌ opa does not win — and now we know why

`bench/depgraph.py`. **The prediction was committed before the results**
(`091fe52`), which is the only thing that makes it a prediction.

> **Corrected by [benchmark 5](#5-large-file-adaptive-chain---the-agent-never-used-the-kernel--in-either-benchmark).**
> The opa arm of this benchmark never called `opa_python` — not once in 96
> sessions. Everything below about what the kernel does or does not save is
> therefore a statement about the *baseline*, not a measurement of the
> kernel, which was never in the comparison. The numbers stand; the
> attribution does not.

Benchmark 3 lost and we blamed the benchmark: a `grep -c | sort` task gives a
persistent kernel nothing to persist. That diagnosis names three conditions, so
this one was built to satisfy all three — an expensive structure (an import
graph over 600 modules, where the pivot needs one reachability run per
candidate), adaptive questions that cannot be batched into a script written in
advance because each names a node the previous answer identified, and eight
turns rather than three.

| metric | baseline | opa | delta (median) |
|---|---|---|---|
| work tokens (input+output) | 5,084 | 4,410 | −13% |
| cost (USD) | $0.340 | $0.340 | **+0.1%** |
| agent turns | 17.5 | 17.5 | 0% |
| wall clock | 84,468 ms | 71,022 ms | −16% |
| n | 4 | 4 | all 8/8 correct, every run |

Ranges overlap on every metric (work tokens: baseline 4,088–5,120, opa
3,805–5,916). **There is no effect here.** The prediction — a token win smaller
than 22%, a wall-clock loss — was wrong in both directions and wrong about the
mechanism.

### Why, traced rather than guessed

Running a baseline session under `--output-format stream-json`:

```
turn 1  Bash: python3 -c "…parse 600 files, build graph, BFS…"  → 3 chars back
        answer 362
turn 2  Bash: python3 -c "…parse 600 files, build graph again…"  → 16 chars back
        answer mod_016.py
turn 3  (no tool call at all)                                     billed 100
        answer 99
```

The baseline **does** rebuild the entire graph from scratch on turn 2 — exactly
the waste the kernel is supposed to remove. It costs almost nothing, because the
rebuild happens inside the shell and only a 16-character answer comes back.

> Rebuilding costs the baseline almost nothing, because the data was never in
> its context to begin with — a competent agent computes over it out of process.
> What a kernel could save here is re-*emitting the script*, a few hundred
> tokens.

(Written at the time as "a persistent kernel does not save you the data, it
saves you re-emitting the script". True of the baseline, but stated as though we
had measured the kernel. We had not — see the banner above.)

Turn 3 is the same lesson from the other side: no tool call, 100 tokens, because
turn 2's script had already printed the number. The agent's own context is
already a cache.

### What this rules in, and what is left

The three conditions we derived from benchmark 3 were not enough, because they
were about **recomputation cost measured in CPU**, and CPU is not what an agent
pays for. Re-parsing 600 files takes 0.1 s and zero context.

So the remaining live hypothesis is narrower and we have **not** tested it: state
that is expensive to rebuild *in wall-clock*, not in tokens — a loaded ML model,
a warmed database connection, a parsed multi-gigabyte dataset, an established
network session. There the kernel holds something the filesystem cannot, and
`python3 -c` genuinely has to pay for it again.

**Until that is measured, this repository has no evidence that the persistent
kernel saves tokens, and does not claim it does.** Four benchmarks have now
looked and found nothing — though benchmark 5 shows that what they found nothing
*in* was a comparison the kernel never entered. Either way the kernel is
documented as external working memory rather than as a saving.

### The fifth wrong measurement

This benchmark reported one `billed_tokens` = input + output + cache_creation.
Two of seven baseline runs came in at 23–29k on turn 1 against ~1.2k for the
rest, and it was read as a variance finding — the kernel removing catastrophic
outliers.

The data disagreed. Those runs cost **$0.005 per 1k tokens against $0.035** for
every other run, with identical tool-call counts and wall clock. Tracing turn 1
thirteen times produced no oversized tool result and no blowup at all. It was
prompt-cache creation: whether an invocation writes the cache or reads it depends
on what else ran on the machine recently.

> An agent's token usage is not a property of the task alone. Any measurement
> spanning separate CLI invocations is measuring cache state too, and has to say
> which it means.

`work_tokens`, `cache_write`, `cache_read` and `cost_usd` are now recorded
separately. Upstream Prime Agent's own `Usage` record draws the same distinction,
which is mild evidence it is the right one. The old file is kept as
`depgraph-INVALID-cache-writes-counted-as-work.json`.

### Five design rounds, all before any agent ran

Each removed a way to score well without doing the work, and each is a way a
graph benchmark can quietly become trivial:

1. The most-depended-on module is a **sink** in any DAG, so asking about its
   imports had no answer and the last three questions collapsed.
2. Ranking globally instead of within root's reachable set named modules root
   cannot reach — making "how much would deleting it disconnect" zero by
   definition.
3. Ranking by in-degree always landed on a late near-leaf, because cross edges
   accumulate on high indices: closure 2, disconnects nothing.
4. Root's direct imports each head a whole subtree, so one of them always won the
   cut-vertex question — guessable between three names.
5. Every module was reachable, so question one was `ls | wc -l`.

What survives carries a trap that confirms the chain cannot be shortcut: the
pivot's transitive closure is 195, but deleting it disconnects only 99, because
the other 96 survive by a cross edge. The naive answer is available and wrong.
All eight ground-truth answers are cross-checked by an independent
implementation — BFS against the generator's DFS, topological DP against its
recursive longest-path.

---

## 5. Large file, adaptive chain  ⚠ the agent never used the kernel — in either benchmark

`bench/bigdata.py`. 8 million rows, 337 MB, eight adaptive questions. The
prediction was committed before the run, in `7807f46`.

Before building it, the boundary condition was measured directly, since a
filesystem is itself a cache:

| rows | csv | rebuild | pickle write | pickle read | reload/rebuild |
|---:|---:|---:|---:|---:|---:|
| 500,000 | 21 MB | 0.4s | 0.2s | 0.1s | 20% |
| 2,000,000 | 84 MB | 1.6s | 1.0s | 0.3s | 21% |
| 8,000,000 | 337 MB | 6.2s | 5.7s | 1.6s | 25% |

The prediction: the baseline would rebuild every turn rather than cache, and opa
would win wall clock by 25–40%.

| metric | baseline | opa | delta (median) |
|---|---|---|---|
| wall clock | 154,575 ms | 147,681 ms | −4.5% |
| work tokens | 2,456 | 2,134 | −13% |
| cost (USD) | $0.233 | $0.279 | **+20%** |
| n | 3 | 3 | all 8/8 correct |

Ranges overlap on every metric. Another null — but the reason is not the one any
of the previous write-ups assumed.

### The agent never called `opa_python`. Not once.

Counting kernel executions on disk across every session both benchmarks created:

| benchmark | opa-arm runs | turns with the kernel attached | turns that called it |
|---|---:|---:|---:|
| 4 — import graph | 12 | 96 | **0** |
| 5 — 8M-row file | 3 | 24 | **0** |

Counted from the kernel's own session directories on disk, one per CLI
invocation. The import-graph figure includes runs later discarded for a token
accounting fault — that fault does not touch which tool the agent reached for,
and excluding them changes 96 to 32 and nothing else.

**120 turns, zero calls.** The tool was attached and listed on every one of
them. A further three turns, hand-traced afterwards, behaved the same way. Tracing a session shows what happened instead:

```
turn 1  Bash: awk -F, 'NR>1{print $2}' events.csv | sort -u | wc -l   → 8 chars
turn 2  Bash: awk -F, 'NR>1{sum[$3]+=$5} END{...}' events.csv         → 85 chars
turn 3  Bash: awk -F, 'NR>1 && $3=="apac"{...}' events.csv            → 102 chars
```

Both arms did this. Identical approach, identical tool, and the opa arm simply
ignored the kernel sitting next to it.

### What this means, and what it costs us

Everything written above about the kernel has to be restated. These benchmarks
did not compare a persistent kernel against a shell. They compared **a shell
against a shell with an unused MCP server attached** — which is why the deltas
are noise. The honest reading:

> The agent never chose the kernel, so benchmarks 3, 4 and 5 measure the *cost
> of offering* it, not the *value of using* it. That cost is approximately
> zero, which is worth knowing. The value remains unmeasured.

And the reason it was never chosen is not a failure of the tool description. It
is that **`awk` is the right answer to these questions.** A streaming aggregation
over a file never materialises an intermediate structure, so there is nothing for
a kernel to hold. Our premise — that the agent builds state worth preserving —
is what the task never called for.

That also revises benchmark 4's conclusion. "A persistent kernel saves you
re-emitting the script, not the data" was right about the baseline and wrong to
present as a measurement of the kernel: the kernel was not in the comparison.

### What would actually test it

A task where the state cannot be streamed out of a file:

- data that arrives from an API or a computation rather than a path `awk` can open
- an index that takes minutes to build and is queried unpredictably
- anything process-resident — a loaded model, an open connection, a GPU context

Until one of those is measured, this repository has **no measurement of the
persistent kernel at all**, and says so. What it does have is three benchmarks
showing that attaching opa to a shell-friendly task costs nothing and gains
nothing, and one showing that a model given `awk` will reach for `awk`.

---

## What we are not claiming

- No claim that opa reduces tokens in general. Benchmarks 0 and 3 show the
  opposite, and benchmarks 4 and 5 show no effect at all.
- **No claim about the persistent kernel in either direction.** Across 123
  sessions in the two benchmarks built to test it, the agent never invoked it
  once — so its value has not been measured, only the (negligible) cost of
  offering it.
- No claim that sub-agent fan-out is worth its cost on a codebase of any size we
  have actually measured. Reuse is measured and wins; fan-out is measured and
  loses.
- n is small (3–7) and single-machine. Treat these as directional.
- Only Sonnet. A weaker model would likely struggle more with rediscovery, which
  should *widen* benchmark 1's gap and shrink benchmark 2's; untested.

## What would sharpen this

- ~~A benchmark where intermediate state is genuinely expensive to rebuild (an
  AST or dependency graph queried across many turns)~~ — done, twice.
  [Benchmark 4](#4-import-graph-adaptive-chain---opa-does-not-win--and-now-we-know-why)
  is the dependency graph and found nothing; benchmark 5 tests the wall-clock
  version. What is still open after both is state that cannot be *serialised* at
  all — a loaded model, an open connection, a GPU context — because a filesystem
  turns out to be a good enough cache for everything else (see the rebuild vs
  reload table in benchmark 5).
- A run across a context compaction, where kernel state survives and context does
  not — the case opa is actually designed for.
- A clean wall-clock comparison under serial blocking work. Benchmark 0- only
  managed one run where both arms did the same thing. Forcing equal verification
  — rather than measuring it after the fact — is the missing piece.
- Whether ownership really is what drives the verification difference, or whether
  it is an artifact of one prompt describing four jobs and the other describing one.
- The same comparison against an in-process child. Upstream does not pay the
  boot, so its fan-out economics are different from ours by construction, and we
  have measured only ours.
- Whether H2 (focused context finds more defects) is real. It needs n far larger
  than 2 and a defect set that is not four planted needles.
- A weaker/cheaper model, where the rediscovery penalty should be larger.
