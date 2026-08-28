# open-primeagent

**Bring RLM to the coding agent you already use.**

An MCP server that gives Claude Code / Codex / opencode three things they don't
have: a **persistent Python kernel** as external working memory, **long-lived
sub-agent sessions** you can re-task later, and a **continual harness** that
accumulates what the project taught you.

Ported from the architecture of
[Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent).
**You don't switch agents. You add one MCP server.**

```bash
claude mcp add opa -- uvx open-primeagent
```

[Install](#install) · [Why this is small](#why-this-is-only-3k-lines-and-not-170k) ·
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
                              adapters: claude-code · codex
✅ L3  Continual Harness      prompts / memory / skills / sub-agent specs
                              + projection into the files your agent already reads
✅ L4  Long-run               goal / schedule / autonomous gate loop
```

Everything marked ✅ is verified by tests that actually spawn a kernel and a real
child agent. See [the roadmap](docs/roadmap.md) for the exit criteria of each phase.

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
that had already read the file cost **one fifth** of a fresh one (23,058 → 1,987
tokens, n=4, tiny variance).

So the value in sub-agents is not parallelism — it is that **the child
persists**. Which is what the registry is for, and what "a child is not
disposable" was always supposed to mean.

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

That third result is a fair hit, and the benchmark is the thing at fault: a
shell is *already* an external computer, so a task solvable by one-liners gives
the persistent kernel nothing to persist. **We therefore have no measured
evidence yet that the kernel saves tokens, and this README does not claim it
does.**

One of the sub-agent benchmarks was also invalid on the first attempt — the host
agent kept answering from context instead of re-tasking the child, so it was
measuring the wrong thing. That is
[written up too](bench/README.md#0b-warm-child-vs-cold-child--reuse-wins-by-5x),
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
can rewrite the instructions its host agent operates under, mid-session, and
they take effect from the next turn.** No restart.

We also learned that pushing behavioral instructions through tool *results* gets
correctly flagged as prompt injection by a well-aligned host model, so the
delivery channel has to be the tool *description*. And Claude Code advertises no
`sampling` capability but does support `elicitation` — the server can ask the
*user* for approval mid-call, which is exactly what a promotion gate needs.

Full write-up with the raw data: [docs/concepts/evolution.md](docs/concepts/evolution.md).

The mechanism is the easy part. The hard part is **evaluation** — without a
measurable gate, "evolution" is just drift. We do not ship an automatic
promotion path where nothing can be measured.

## ⚠️ Not a sandbox

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
| [Architecture](docs/architecture.md) · [Roadmap](docs/roadmap.md) | how and what next |
| [Benchmarks](bench/README.md) | measured, including the losses |
| [Security](docs/security.md) | **read this one** |

## License and relationship to Prime Agent

Apache-2.0. This is an **independent reimplementation** inspired by Prime
Agent's architecture, not a fork, and it contains no copied code. The `rlm` API
names and the harness state schema are kept compatible on purpose, so upstream's
documentation and skills stay applicable.
