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

```
uv run python bench/subagents.py --experiment parallel --repeat 3
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

Fanning out to four fresh specialists cost 8.8x. Re-tasking one that was already
warm cost **one fifth** of starting a new one. So the value in sub-agents is not
parallelism — it is that **the child persists**, which is exactly what the
registry exists for and what "a child is not disposable" was always supposed to
mean.

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

## What we are not claiming

- No claim that opa reduces tokens in general. Benchmarks 0 and 3 show the
  opposite.
- No claim that sub-agent fan-out is worth its cost on a codebase of any size we
  have actually measured. Reuse is measured and wins; fan-out is measured and
  loses.
- n is small (3–7) and single-machine. Treat these as directional.
- Only Sonnet. A weaker model would likely struggle more with rediscovery, which
  should *widen* benchmark 1's gap and shrink benchmark 2's; untested.

## What would sharpen this

- A benchmark where intermediate state is genuinely expensive to rebuild (an AST
  or dependency graph queried across many turns), which is the real claim behind
  the persistent kernel.
- A run across a context compaction, where kernel state survives and context does
  not — the case opa is actually designed for.
- The case fan-out should win: a codebase large enough that the parent cannot
  hold the material at all. Benchmark 0 only shows that fan-out loses when the
  work fits in one context, which is not the interesting case.
- A weaker/cheaper model, where the rediscovery penalty should be larger.
