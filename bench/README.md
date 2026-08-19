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

---

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

- No claim that opa reduces tokens in general. Benchmark 3 shows the opposite on
  a shell-friendly task.
- No claim about sub-agent quality or throughput. Not measured yet.
- n is small (3–7) and single-machine. Treat these as directional.
- Only Sonnet. A weaker model would likely struggle more with rediscovery, which
  should *widen* benchmark 1's gap and shrink benchmark 2's; untested.

## What would sharpen this

- A benchmark where intermediate state is genuinely expensive to rebuild (an AST
  or dependency graph queried across many turns), which is the real claim behind
  the persistent kernel.
- A run across a context compaction, where kernel state survives and context does
  not — the case opa is actually designed for.
- Sub-agent benchmarks: parallel specialists versus sequential analysis, and
  re-tasking a warm child versus starting a cold one.
- A weaker/cheaper model, where the rediscovery penalty should be larger.
