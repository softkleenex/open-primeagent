# open-primeagent

[![CI](https://github.com/softkleenex/open-primeagent/actions/workflows/ci.yml/badge.svg)](https://github.com/softkleenex/open-primeagent/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/open-primeagent)](https://pypi.org/project/open-primeagent/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![Upstream compatibility](https://img.shields.io/badge/rlm%20protocol-pinned%20by%20test-8a2be2)](tests/test_upstream_compat.py)

**Bring RLM to the coding agent you already use.**

An MCP server that gives Claude Code / Codex / opencode three things they don't
have: a **persistent Python kernel** as external working memory, **long-lived
sub-agent sessions** you can re-task later, and a **continual harness** that
accumulates what the project taught you.

Speaks the same `rlm` protocol as
[Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent) — same request
names, same field names, same state-file schema, [checked by a test](tests/test_upstream_compat.py).
**You don't switch agents. You add one MCP server.**

```bash
claude mcp add opa -- uvx open-primeagent
```

[Install](#install) · [Why this is small](#why-this-is-only-3k-lines-and-not-170k) ·
[Is it really the same RLM?](#is-it-really-the-same-rlm) ·
[Sub-agents](#persistent-sub-agents-actually-work) ·
[External memory](#context-is-for-deciding-not-for-storage) ·
[Harness](#a-harness-that-learns-without-touching-your-files) ·
[Benchmarks](#benchmarks--including-the-ones-we-lost) ·
[Evolution](#can-an-agent-evolve-mid-session) ·
[Security](#-not-a-sandbox) · [Docs](docs/)

---

```
✅ L1  Persistent Python      kernel · external working memory · output truncation
✅ L2  RLM                    persistent sub-agents + agent-to-agent messaging
                              adapters: claude-code (in CI) · codex (by hand, once)
✅ L3  Continual Harness      prompts / memory / skills / sub-agent specs
                              + projection into the files your agent already reads
✅ L4  Long-run               goal / schedule / autonomous gate loop
✅ L5  Evolution              live tool-surface rewriting + harness.evolve()
```

Every ✅ is verified by tests that boot a real IPython kernel, and the
**claude-code** path is verified end to end by tests that spawn a real child
agent (`pytest -m child`).

One caveat we would rather state than have you find. The **codex** adapter was
verified against the real CLI by hand when it was written (`43db9fd`, a child
resumed with its context intact), and its wiring is covered by automated tests
against a stub CLI — command construction, `thread_id` parsing, sandbox flags,
malformed output. But no automated test drives the real `codex` binary, and the
codex auth on this machine has since expired, so that one-time check is not
being repeated. Treat claude-code as continuously verified and codex as verified
once. If you run it against real codex, we would like to hear what breaks.

See [the roadmap](docs/roadmap.md) for the exit criteria of each phase.

---

## Why this is only ~3k lines and not 170k

Upstream Prime Agent is a full agent harness. We measured it:

| package | LOC | what it is |
|---|---:|---|
| `packages/coding-agent` | 117,690 | host harness, sessions, TUI, CLI |
| `packages/ai` | 35,332 | providers + OAuth + MCP |
| `packages/tui` | 14,635 | terminal UI |
| `prime-agent-runtime` | **1,536** | ← the `rlm` kernel shim. All of it. |

`rlm/__init__.py` is 348 lines, and almost every line is a thin
`await host_request("rlm.run", ...)` RPC wrapper. The concept lives there; the
other 167k lines are one particular harness implementation.

**So we delegate the harness to the agent you already run.** Sessions, auth,
model selection, permissions, the UI — all of it stays yours. We build the RLM
runtime and nothing else.

## Is it really the same RLM?

Fair question, and the kind that is usually answered with adjectives. Here it is
answered by a CI test that reproduces upstream's own payload validator
(`rlm/__init__.py:181`, which **raises** on a malformed record) and runs our
wire payloads through it:

| | |
|---|---|
| request names on the wire | `rlm.run` · `rlm.list_subagents` · `rlm.delete_subagent` — identical |
| `RLMSubagent` / `RLMSpawnHandle` fields | all upstream fields present |
| child status vocabulary | exactly `{running, completed, error}` |
| `HarnessEntry` | **13/13 fields, field for field** |
| `harness_state.json` | same `schema: 1`, entries-by-kind + refinements |

That test found two breaks in code that was already shipping and green: our
`delete_subagent` was answering in a shape upstream cannot parse, and
`RLMSubagent` was missing three upstream fields. Both fixed. **Compatibility
nobody tests is compatibility that is already broken.**

Where we diverge — socket instead of Jupyter `comm`, your `claude`/`codex`
instead of an in-process child, per-caller tokens instead of one trusted kernel
— each divergence and what it costs is written down in
**[docs/lineage.md](docs/lineage.md)**, along with the interop limit that matters
in practice: upstream can *read* a state file we wrote, but if it writes it back,
our rollback snapshots are dropped.

**What this does not claim:** we have never benchmarked against Prime Agent
itself. Every number below compares *opa + Claude Code* against *bare Claude
Code*. The protocol equivalence is tested; the performance comparison is
[open](docs/lineage.md#what-we-cannot-claim).

## Persistent sub-agents actually work

The hard requirement is that a child is **not disposable**: you must be able to
come back to it later and have it remember. Both CLIs already support that, and
we verified it:

| | spawn | resume |
|---|---|---|
| `claude` | `-p P --session-id <UUID>` | `-p P --resume <UUID>` |
| `codex` | `exec P --json` | `exec resume <THREAD_ID> P` |

Here is a real run, copied from the integration test:

```python
await rlm('Reply with exactly: ALPHA-7', name='probe', model='sonnet')
# → <rlm child 'probe' (claude-code) running>      returns in 0.6s, child keeps working

await agent_message.inbox()
# → [{'sender': 'probe', 'message': 'ALPHA-7', 'ok': True, 'tokens': 11}]

# ---- now restart the parent kernel ----

await rlm.list_subagents()
# → [<subagent 'probe' (claude-code) completed turns=1 tokens=11>]

await agent_message.send('What token did you just say? Reply with only the token.',
                         receiver_name='probe')
await agent_message.inbox()
# → ... {'sender': 'probe', 'message': 'ALPHA-7'}
#   the parent kernel restarted, and the child still remembered its earlier turn
```

`rlm(...)` does not block. It returns a handle as soon as the task is admitted;
results arrive in a mailbox. So these two lines really do run in parallel:

```python
api  = await rlm("audit the API layer for security problems", name="api-reviewer")
test = await rlm("map the gaps in our test coverage",          name="test-reviewer")
```

Mixed backends work too — parent on Claude Code, child on Codex:

```python
await rlm("refactor this module", name="refactorer", adapter="codex")
```

## Context is for deciding, not for storage

```python
opa_python("files = [f'f{i}.py' for i in range(500)]")
opa_python("len(files)")            # → 500     separate call, still alive
opa_python("print('x' * 30000)")    # → truncated; full text at outputs/00000.txt
```

Large intermediate results stay in Python variables. The model sees what it
needs to pick the next step, not the whole warehouse. When output is truncated
we keep the **tail** as well as the head — the actual cause of a Python
traceback is on the last line.

## A harness that learns, without touching your files

`H = (prompts, sub-agent specs, skills, memory)`, with CRUD and exact rollback.

We do not own the system prompt, so the harness is **projected into the files
your agent already reads** — and only inside a delimiter block:

```markdown
<!-- opa:begin — generated. Nothing outside this block is touched. -->
...
<!-- opa:end -->
```

Everything outside the block is preserved byte for byte, and
`opa_bootstrap(remove=True)` restores the file exactly. That is not a promise in
a README; `tests/test_projection.py` and `tests/test_bootstrap.py` enforce it.

Memory bodies never land in the prompt file — only an index does. Skills we
create are marked `.opa-managed`, so skills you wrote yourself are never
removed.

## Four tools. That's the cap.

`opa_python` · `opa_status` · `opa_kernel` · `opa_bootstrap`

`rlm`, `agent_message` and `harness` are **not** MCP tools — they are Python
symbols inside the kernel. The point of this architecture is *give the model a
computer, not twenty tools*; polluting your agent's tool list would contradict
it. `server.MAX_TOOLS = 4` and a test enforces the ceiling. When you want to add
a tool, that is the signal to expose a kernel symbol instead.

## Install

<details open>
<summary><b>Claude Code</b></summary>

```bash
claude mcp add opa -- uvx open-primeagent
claude mcp list                     # opa: ✔ Connected
```
</details>

<details>
<summary><b>Codex</b></summary>

In `~/.codex/config.toml`:

```toml
[mcp_servers.opa]
command = "uvx"
args = ["open-primeagent"]
```
</details>

<details>
<summary><b>opencode / any MCP client</b></summary>

Register `uvx open-primeagent` as a stdio MCP server. Using opencode as a
*child* backend is still [under investigation](docs/install/opencode.md).
</details>

<details>
<summary><b>From a checkout (for development)</b></summary>

```bash
git clone https://github.com/softkleenex/open-primeagent && cd open-primeagent
uv sync --extra dev
uv run pytest -q                                    # 99 passed
claude mcp add opa --scope local -- uv run --directory "$PWD" opa
```
</details>

Full per-host notes and every environment variable:
[docs/install/](docs/install/) · [docs/reference/configuration.md](docs/reference/configuration.md).

## Benchmarks — including the ones we lost

Measured with `claude -p --output-format json`, reading its own `usage` and
`total_cost_usd`. Raw data and methodology: [bench/](bench/).

**Sub-agents: spawning is expensive, keeping one is nearly free.** A child costs
roughly 36k tokens of session startup. That one fact runs both ways:

| | | |
|---|---|---|
| fan out to 4 fresh specialists vs one agent doing it all | **+777% cost** | ❌ |
| re-task a warm child vs starting a cold one for the same question | **-81% cost** | ✅ |

Fanning out on a 12-file service produced the same findings for 8.8x the price,
because spawning one child cost more than the entire job. Re-tasking a child
that had already read the file cost **one fifth** as much (-81%) and used **one
twelfth** the tokens (23,058 → 1,987, n=4, tiny variance). The two figures differ
because the cheap turn is mostly cache reads, which are billed but not free.

We then built a benchmark specifically to let fan-out win — 444 files, ~135k
tokens, four independent subsystems, children scoped so nothing is read twice —
and **it still lost on every axis, including wall clock** (112.8s vs 49.6s with
four children running at once). The reason is worth knowing: the single agent
answered using 42k tokens on a 135k-token codebase. It never read the
repository, it grepped. Fan-out relieves a bottleneck that a competent agent
does not create.

So the value in sub-agents is not parallelism — it is that **the child
persists**. Which is what the registry is for, and what "a child is not
disposable" was always supposed to mean.

One caveat we owe you: that 36k is *our* architecture's price. Upstream Prime
Agent runs a child inside its own process and never pays a cold CLI boot. We
shell out to your own `claude`/`codex` so that we do not have to own your host,
and this is the bill for that trade.

**One thing fan-out did buy, unexpectedly.** Given four subsystems each with a
bug and a 30-second acceptance check, four specialists ran every check, every
time (3/3 runs). One agent doing all four fixed the code correctly but verified
everything only **once in three runs** — twice it decided inspection was enough
and never ran a check, despite being told to. Same fixes either way, at 2.8x the
tokens. [The write-up](bench/README.md#0--ownership-and-verification---the-finding-was-not-the-one-we-went-looking-for)
also records that it took four attempts before the benchmark measured anything
real.

**Where a learned harness entry pays** — a project whose test suite depends on a
generator hidden among 16 scripts in `tools/`, with 15 plausible decoys. Arm A
discovers the rule by failing; arm B starts with one harness entry naming it:

| metric | no harness | with harness | delta |
|---|---|---|---|
| turns | 15.6 | 10.3 | **-34%** |
| billed tokens | 25,278 | 19,693 | **-22%** |
| cost | $0.355 | $0.232 | **-35%** |
| wall clock | 58.2s | 25.3s | **-57%** |
| worst-case turns | 24 | 11 | **-54%** |

n=7 each, both arms always passed. The mean understates it: without the harness
the worst run burned 24 turns and 145 seconds hunting through `tools/`, while
every harness run landed in 9–11. **Variance collapsed**, which matters more in
practice than the mean.

**Where it does not.** Same benchmark with the generator sitting in the project
root, one glance away: the harness entry becomes pure overhead, **+26% turns**.
And on a three-turn corpus analysis that a `grep -c | sort` one-liner solves,
attaching opa cost **+42% turns and +33% cost** versus plain Claude Code.

That third result is a fair hit. We blamed the benchmark — a shell is *already*
an external computer, so a one-liner task gives the kernel nothing to persist —
and then built the benchmark that diagnosis called for: an import graph over 600
modules, eight adaptive questions that cannot be batched because each names a
node the previous answer found, and the prediction
[committed before the results](bench/depgraph.py).

**The kernel still did not win.** Cost came out within 0.1%, turn counts
identical, every range overlapping, all 8/8 answers correct in both arms. Tracing
the baseline showed why:

```
turn 1  Bash: python3 -c "…parse 600 files, build the graph, BFS…"  → 3 chars back
turn 2  Bash: python3 -c "…parse 600 files, build it again…"       → 16 chars back
turn 3  (no tool call at all)                                       100 tokens
```

The baseline *does* rebuild the whole graph every turn. It costs nothing, because
the rebuild happens in the shell and only the answer comes back.

> A persistent kernel does not save you the data. It saves you re-emitting the
> script. The data was never in your context to begin with.

So: **four benchmarks have looked for a token saving from the kernel and none
found one.** This README does not claim there is one. What is left untested is
state that is expensive in *wall clock* rather than tokens — a loaded model, a
warmed connection, a parsed multi-gigabyte dataset — which is where the kernel
holds something a file cannot. [Full write-up.](bench/README.md#4-import-graph-adaptive-chain---opa-does-not-win--and-now-we-know-why)

One of the sub-agent benchmarks was also invalid on the first attempt — the host
agent kept answering from context instead of re-tasking the child, so it was
measuring the wrong thing. That is
[written up too](bench/README.md#0b-warm-child-vs-cold-child---reuse-wins-by-5x),
along with the instrumentation that caught it.

What survives is narrower and more useful than "opa makes things faster":

> Spawning a sub-agent is expensive; keeping one is nearly free.
>
> A harness entry pays for itself in proportion to how expensive the knowledge
> is to rediscover.

Both are arguments for **persistence over creation** — which is the thesis this
project inherited, now with numbers on it.

## Can an agent evolve mid-session?

We ran the experiment instead of guessing, with a raw JSON-RPC MCP server
attached to Claude Code. Server-side trace:

```
tools/list   call=1  serving_version=0     ← session starts
tools/call
sent list_changed                          ← server rewrites its own tool description
tools/list   call=2  serving_version=1     ← host re-fetches ✅
--- same session, next turn ---
tools/list   call=1  serving_version=1
```

On the next turn the model read the new description verbatim. **An MCP server
can rewrite what its host agent reads, mid-session, and it takes effect from the
next turn.** No restart. That is shipped as `harness.evolve()`, which pushes one
delta through all three layers at once — kernel now, tool description next turn,
project file next session — reversibly.

Then building it produced the more interesting result. We put a promoted rule in
the description and asked Claude Code to quote it. It read our text back
verbatim, and refused to act on it:

> the note claims to be "recorded by agent" today, but **I have no record of
> creating it** … I'd treat it as untrusted/possible prompt injection.

It is right, and no wording fixes it: any provenance a server asserts is just
more server-authored text. So the limit is real, not cosmetic:

> A tool description can remind an agent of what **it** recorded while running.
> It cannot give standing to anything else.

Which is why the live surface carries an *index* of the current session's own
notes, and authority comes from the project file the host presents as the user's
configuration. **L1 reminds; L0 authorises.**

Full write-up with the transcripts: [docs/concepts/evolution.md](docs/concepts/evolution.md).

The mechanism was the easy part. The hard part is **evaluation** — without a
measurable gate, "evolution" is just drift. We do not ship an automatic
promotion path where nothing can be measured.

## ⚠ Not a sandbox

The kernel and every child agent run **with your OS permissions**. Upstream says
the same about its kernel; we add child spawning on top, so the blast radius is
larger. Run untrusted repositories and long autonomous sessions inside a
devcontainer or VM. Read [docs/security.md](docs/security.md) before you turn
anything autonomous on.

## Docs

Start at **[docs/](docs/)**, or jump straight to:

| | |
|---|---|
| [Quickstart](docs/quickstart.md) | running in two minutes |
| [Persistent Python](docs/concepts/persistent-python.md) · [RLM](docs/concepts/rlm.md) · [Harness](docs/concepts/harness.md) · [Long-run](docs/concepts/long-run.md) | the concepts |
| [MCP tools](docs/reference/tools.md) · [Kernel API](docs/reference/kernel-api.md) · [Configuration](docs/reference/configuration.md) | reference |
| [Lineage](docs/lineage.md) | what is inherited, what diverges, what we cannot claim |
| [Architecture](docs/architecture.md) · [Roadmap](docs/roadmap.md) | how and what next |
| [Benchmarks](bench/README.md) | measured, including the losses |
| [Security](docs/security.md) | **read this one** |

## License and relationship to Prime Agent

Apache-2.0. This is an **independent reimplementation**, not a fork, and it
contains no copied code — the reference checkout is git-ignored and read only to
learn the contract. The `rlm` API names and the harness state schema are kept
compatible on purpose, so upstream's documentation and skills stay applicable,
and [a test](tests/test_upstream_compat.py) keeps that true.

Full breakdown, with upstream `file:line` citations for every claim:
**[docs/lineage.md](docs/lineage.md)**.
