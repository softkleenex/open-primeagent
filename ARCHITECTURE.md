# ARCHITECTURE

> `open-primeagent` (package `opa`) — Prime Agent's RLM architecture, rebuilt so
> it attaches to the coding agent you already run instead of replacing it.

---

## 0. The one constraint

Everything below follows from a single rule:

> **We do not replace the host agent.**
> A Claude Code / Codex / opencode user keeps their environment, auth, settings
> and skills, and gets RLM by registering one MCP server.

Consequences:

| | Prime Agent | open-primeagent |
|---|---|---|
| host | its own TS harness (117k LOC) | **the agent you already run** |
| system prompt | owns it | cannot touch it → works around it via *projection* |
| kernel bridge | Jupyter comm → TS host | Unix socket → MCP server |
| child sessions | its own session manager | the host CLI's `--session-id` / `resume` |
| model selection | its own provider layer | delegated to the host CLI (`--model`) |

The only thing we actually build is the **RLM runtime**. Everything else is
delegated.

### Evidence from the upstream repo

Measured on `_ref/prime-agent`:

```
packages/coding-agent   117,690 LOC (TS)   host harness / sessions / TUI / CLI
packages/ai              35,332 LOC (TS)   providers + OAuth + MCP
packages/tui             14,635 LOC (TS)   terminal UI
prime-agent-runtime       1,536 LOC (Py)   ← the rlm kernel shim, in full
```

`prime-agent-runtime/src/rlm/__init__.py` is 348 lines and is almost entirely
thin `await host_request("rlm.run", ...)` RPC wrappers. `harness.py` (820 lines)
is a CRUD store over `harness_state.json`.

**The conceptual core of RLM fits in 1.5k lines; the rest is one harness
implementation.** Delegating the harness makes this project a realistic size.

---

## 1. Layers

```
┌──────────────────────────────────────────────────────────────┐
│  L4  Long-run     goal / heartbeat / schedule / autonomous   │
├──────────────────────────────────────────────────────────────┤
│  L3  Continual Harness   H = (ρ prompts, G subagents,        │
│                               K skills,   M memory)          │
│                          + projection into host-read files   │
├──────────────────────────────────────────────────────────────┤
│  L2  RLM          persistent sub-agents + A2A messaging      │
│                   ├ registry (survives restarts)             │
│                   └ adapters: claude-code / codex / opencode │
├──────────────────────────────────────────────────────────────┤
│  L1  Persistent Python   IPython kernel as working memory    │
├──────────────────────────────────────────────────────────────┤
│  L0  Session & Store     session dir / JSONL trajectory      │
└──────────────────────────────────────────────────────────────┘
```

Dependencies point downward only. There is no L2 without L1, and `G` in L3 is
meaningless without L2. Implementation order follows the same line.

---

## 2. Runtime topology

```
        the coding agent you already run (Claude Code / Codex / opencode …)
                              │
                              │  MCP (stdio)
                              ▼
        ┌───────────────────────────────────────────┐
        │            opa MCP server (host)          │
        │                                           │
        │   tools:  opa_python  opa_status          │
        │           opa_kernel  opa_bootstrap       │
        │                                           │
        │   ┌─────────────┐    ┌──────────────────┐ │
        │   │ HostBridge  │◄──►│ RLM registry     │ │
        │   │ (unix sock) │    │ harness store    │ │
        │   └──────▲──────┘    │ goal / schedule  │ │
        │          │           └──────────────────┘ │
        └──────────┼────────────────────────────────┘
                   │ JSONL RPC over $OPA_HOST_SOCKET
                   ▼
        ┌───────────────────────────────────────────┐
        │        persistent IPython kernel          │
        │                                           │
        │   preloaded:  rlm  harness                │
        │               agent_message               │
        │   user state: files, results, graphs, …   │
        └───────────────────────────────────────────┘
                   │ adapters spawn subprocesses
                   ▼
        ┌──────────┬──────────┬──────────┬──────────┐
        │ backend  │ frontend │ test     │ security │  ← child agents
        │ (claude) │ (claude) │ (codex)  │ (claude) │    each with its own session
        └──────────┴──────────┴──────────┴──────────┘
```

### Why a Unix socket instead of a Jupyter comm

Upstream has the kernel call `Comm(target_name="host.request")` into the TS
host. That requires runtime-patching the kernel's `control_handlers` so comm
replies can arrive during an `execute_request`
(`__init__.py:_install_control_comm_handlers`).

We use a socket instead:

- It is **independent of kernel restarts** — the bridge is not tied to a kernel
  channel.
- Processes that are not the kernel (skill subprocesses, child agents) can call
  the host through the same door — required for L3 and for child → parent push.
- The bridge is testable on its own, with no kernel running.
- Give a child `OPA_HOST_SOCKET` + `OPA_ROLE=child` and it can message its
  parent. That is the precondition for two-way A2A.

Protocol: one request per connection, one line of JSON.

```
→ {"id":"1","type":"rlm.run","payload":{...}}
← {"id":"1","status":"ok","result":{"rlm_child_id":"opa-a1b2","name":"api-reviewer",...}}
← {"id":"1","status":"error","error":"..."}
```

Handler results are **wrapped in `result`**. Merging them flat lets a handler
key shadow a protocol key — and it did: `rlm.run` returned `status: "running"`,
which overwrote the protocol's `status: "ok"` and broke the client. A naming
convention would break again later, so the envelope makes it structurally
impossible.

Request type names match upstream (`rlm.run`, `rlm.list_subagents`,
`rlm.delete_subagent`, `rlm.find_models`) so upstream docs and skills still
apply.

Line size limit is 8 MB, set explicitly on **both** ends. `asyncio`'s
`StreamReader` defaults to 64 KiB, which silently breaks large prompts and any
inbox holding a few child reports.

---

## 3. The MCP tool surface is deliberately tiny

Prime Agent's thesis is *don't give the LLM twenty tools, give it Python*.
Polluting the host's tool list would contradict that thesis and degrade the
agent the user already has. So the surface is capped at **four**.

| tool | role |
|---|---|
| `opa_python(code, timeout=…)` | the only work tool; runs in the persistent kernel |
| `opa_status()` | one page: kernel / children / goal / harness |
| `opa_kernel(action)` | `restart` \| `interrupt` \| `info` |
| `opa_bootstrap(agent, remove)` | project the harness into host-read files |

`rlm`, `harness`, `agent_message` and `goal` are **kernel symbols, not tools**.

```python
# this is all the host agent actually does
opa_python("""
api  = await rlm("audit the API layer", name="api-reviewer")
test = await rlm("map test coverage gaps", name="test-reviewer")
""")
```

`server.MAX_TOOLS = 4`, enforced by `tests/test_server.py`.

---

## 4. L1 — Persistent Python

- One IPython kernel per session, owned via `jupyter_client.AsyncKernelManager`.
- The kernelspec is written by us with `argv[0] = sys.executable`. Relying on
  the user's installed kernelspec would boot a Python without `opa_runtime`, and
  the `rlm` symbols would silently vanish.
- Top-level `await` is handled natively by IPython's autoawait. Upstream uses
  `nest_asyncio`; we measured that it is unnecessary and dropped the dependency.
- Transport is an **IPC socket** on POSIX. TCP sends kernel code and output in
  cleartext over localhost (ipykernel warns about this itself). `jupyter_client`
  uses `ip` as the socket path prefix for IPC, and macOS caps `sun_path` at 104
  bytes, so we use a short temp-dir prefix and fall back to TCP if it would not
  fit.
- Output policy: return a truncated view, write the full text to the session
  directory, and hand back the path. This is what "don't use context as a
  warehouse" means concretely. Default `OPA_MAX_OUTPUT_CHARS=4000`.
- Truncation keeps head **and tail** — the real cause of a traceback is on the
  last line, so a head-only cut is the least useful possible cut.
- A kernel restart clears user variables. Everything that must survive (child
  registry, harness, goal) lives on the host's disk.

---

## 5. L2 — RLM (persistent sub-agents)

### 5.1 The adapter contract

```python
class AgentAdapter(Protocol):
    name: str
    def available(self) -> bool: ...
    def preassign_session_id(self) -> str | None: ...
    async def run(self, request: TurnRequest) -> TurnResult: ...
```

A backend qualifies if it can do exactly two things: run non-interactively from
a prompt, and **resume by session id**. Child persistence comes entirely from
the second one.

| adapter | spawn | resume | session id origin |
|---|---|---|---|
| `claude-code` | `claude -p P --session-id <UUID> --output-format json` | `claude -p P --resume <UUID>` | **we issue it** |
| `codex` | `codex exec P --json --skip-git-repo-check` | `codex exec resume <TID> P --json` | codex issues it → parsed from `thread.started` |
| `opencode` | (to investigate) | (to investigate) | — |

Being able to choose the UUID for `claude` matters: the registry id and the
native session id map 1:1, which keeps recovery trivial.

**Constraints found by running them** (2026-08-19):

- Both CLIs need **stdin closed**. Left open as a pipe, `codex` blocks forever on
  `Reading additional input from stdin...`.
- `codex` refuses to run outside a git repository without `--skip-git-repo-check`.
- Both resume with earlier context intact. That is the basis for RLM persistence.

codex JSONL events: `thread.started.thread_id` is the session id,
`item.completed.item.text` (type `agent_message`) is the final answer,
`turn.completed.usage` carries tokens.

### 5.2 Child registry

`rlm(...)` **does not wait for a result.** Like upstream, it returns a handle the
moment the task is admitted.

```python
@dataclass
class ChildRecord:
    rlm_child_id: str        # opa-<8hex>
    name: str                # "api-reviewer" — the address for re-tasking
    adapter: str
    native_session_id: str | None
    cwd: str
    status: Literal["running", "completed", "error"]
    turns: int
    tokens: int
    cost_usd: float
```

Persisted to `children/<id>/child.json` + `turns.jsonl`, so
`await rlm.list_subagents()` returns the same children after a kernel restart,
a context compaction, or a host restart.

Turns for one child are **serialized by a per-child lock**. Two concurrent
`--resume` calls on the same session id race over the same session file and
corrupt its context. Messages are queued, never dropped, and different children
still run in parallel.

### 5.3 A2A messaging

Mailboxes live at `<session>/mailbox/<name>.jsonl`.

- **parent → child**: a new turn via the adapter's resume path. The child keeps
  its earlier context. This is what "a child is not disposable" means in code.
- **child → parent**: today the adapter captures the child's final output into
  the parent mailbox. Next: attach the opa MCP server to the child with
  `OPA_ROLE=child` so it can push mid-run — the reason the bridge is a socket.

### 5.4 Lifetime

```
manager ─┬─ backend  ─┐
         ├─ frontend ─┤  long-lived, re-tasked when needed
         ├─ test     ─┤
         └─ security ─┘
```

Not a one-shot fan-out. `delete_subagent` only ever runs when asked.

---

## 6. L3 — Continual Harness

`H = (ρ, G, K, M)`, kind ∈ `prompt | subagent | skill | memory`,
scope ∈ `local | global`. The `harness_state.json` schema is kept compatible
with upstream so sessions can move between the two.

One deliberate addition: `RefinementEvent.before` holds a snapshot. Upstream
records changes as strings only, which cannot be reverted precisely. Extra
fields are ignored by upstream's loader, so compatibility holds both ways.

### 6.1 Projection — the problem unique to this project

Upstream owns the system prompt, so it can inject the harness directly. We
cannot. So we **project into the files the host already reads**:

| harness kind | projection target |
|---|---|
| `prompt` (ρ) | a delimiter block inside `CLAUDE.md` / `AGENTS.md` |
| `skill` (K) | `.claude/skills/<id>/SKILL.md`, marked `.opa-managed` |
| `memory` (M) | `.opa/memory/*.md`; the block carries **only an index** |
| `subagent` (G) | registry default spec (`--append-system-prompt` at spawn) |

**Invariant: we write only inside the delimiters.**

```markdown
<!-- opa:begin — generated. Nothing outside this block is touched. -->
...
<!-- opa:end -->
```

Nothing outside the block is modified, `remove` restores the file byte for byte,
and skill directories without our `.opa-managed` marker are never deleted. This
is where the promise is kept or broken, so `tests/test_projection.py` and
`tests/test_bootstrap.py` enforce it rather than the documentation.

`opa_bootstrap(agent="auto")` writes only to prompt files that **already exist**.
Creating files the user never had would itself be changing their environment; if
none exist we create the single most portable one, `AGENTS.md`.

### 6.2 Refinement

The harness does **not** decide what to change. Claude Code advertises no MCP
`sampling` capability (measured — see `docs/evolution.md` §1.1), so the host does
not lend us its model. The split is:

- `harness.evidence()` — gather grounds from the trajectory. Only **repeated**
  signals are promotion candidates; a one-off is not a pattern.
- the caller (host agent, or a refiner child) decides the delta.
- `harness.apply(changes, trigger=…)` — apply the minimal CRUD delta. If any
  change fails, everything already applied is reverted; a half-applied harness
  is the worst possible outcome.
- `harness.rollback(event_id)` — exact revert from the `before` snapshot.

Upstream's rules are kept: never modify the base system prompt, prefer the
smallest change, keep refinement history.

---

## 7. L4 — Long-run

| feature | implementation |
|---|---|
| goal | `<session>/goal.json`, exposed via `opa_status()` and the `goal.*` kernel API |
| heartbeat | host-side scheduler pushes reminders into the mailbox |
| schedule | one-time / cron; user-created and agent-created (`rlm_heartbeat`) kept separate |
| autonomous | max turns / token budget / wall clock + a quality gate; a failed gate feeds its output back in |

**A stated limit**: we do not own the host's turn loop. "Waking the agent" is
therefore a pull (collected on the next turn), not a push. Real push requires
opa to drive the children itself in autonomous mode, where the parent also runs
on an adapter.

---

## 8. Security

Upstream states plainly that its IPython kernel and workers are not a security
sandbox. Model-generated Python and shell run with the user's OS permissions.
We additionally spawn children, so the surface is wider.

Defaults:

- Conservative child permissions. `--dangerously-skip-permissions` is
  **explicit opt-in only**; codex children run under `--sandbox workspace-write`.
- A child's `cwd` cannot escape the workspace. Both sides of the comparison are
  resolved, so a symlinked workspace does not produce false rejections.
- The bridge socket is `0600`, so another local user cannot push commands into
  the kernel.
- Long autonomous runs belong in a devcontainer or VM (`docs/security.md`).

---

## 9. Open questions

- opencode's headless / resume interface.
- Recursion depth limits when the opa server is attached to a child.
- Conflict handling for `global` scope across several projects.
- How much of the user's kernel namespace, if any, is worth restoring after a
  restart (upstream restores none).
