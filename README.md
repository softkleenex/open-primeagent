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

---

```
✅ L1  Persistent Python      kernel · external working memory · output truncation
✅ L2  RLM                    persistent sub-agents + agent-to-agent messaging
                              adapters: claude-code · codex
✅ L3  Continual Harness      prompts / memory / skills / sub-agent specs
                              + projection into the files your agent already reads
🚧 L4  Long-run               goal / heartbeat / schedule / autonomous
```

Everything marked ✅ is verified by tests that actually spawn a kernel and a real
child agent. See [ROADMAP.md](ROADMAP.md) for the exit criteria of each phase.

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

## Try it

```bash
git clone https://github.com/softkleenex/open-primeagent && cd open-primeagent
uv sync --extra dev
uv run pytest -q                                    # 99 passed
claude mcp add opa --scope local -- uv run --directory "$PWD" opa
claude mcp list                                     # opa: ✔ Connected
```

Codex, opencode and other MCP clients: see [install/](install/).

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

Full write-up with the raw data: [docs/evolution.md](docs/evolution.md).

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

- [ARCHITECTURE.md](ARCHITECTURE.md) — layers, the host bridge, projection
- [ROADMAP.md](ROADMAP.md) — phases with executable exit criteria
- [docs/evolution.md](docs/evolution.md) — what self-improvement can actually reach
- [docs/security.md](docs/security.md) — read this one

## License and relationship to Prime Agent

Apache-2.0. This is an **independent reimplementation** inspired by Prime
Agent's architecture, not a fork, and it contains no copied code. The `rlm` API
names and the harness state schema are kept compatible on purpose, so upstream's
documentation and skills stay applicable.
