# ROADMAP

Dependency order is the implementation order:
**Persistent REPL → Persistent Sub-agents → Continual Harness → Long-run.**
Each layer is meaningless without the one above it in this list.

Every phase must pass **exit criteria that were actually executed**, not
reasoned about, before the next one starts.

---

## Phase 0 — Skeleton and decisions  ✅ done

- [x] Measured the upstream repo (`_ref/prime-agent`)
- [x] Verified the host CLI adapter contract (session-id · resume · json)
- [x] ARCHITECTURE / ROADMAP / TODO
- [x] `uv sync` passes; the `opa` entry point answers an MCP handshake

**Exit ✅**: `claude mcp add opa --scope local -- uv run --directory <repo> opa`
→ `claude mcp list` shows `opa: ✔ Connected`. Handshake also confirmed with a
raw MCP stdio client (`server: opa 0.0.1`).

---

## Phase 1 — Persistent Python  (L1)  ✅ done

One idea: *stop using the model's context as a warehouse.*

- [x] `KernelManager` — one IPython kernel per session; boot / restart / interrupt
- [x] `opa_python` — execute, capture, **truncate + store the full text**
- [x] ~~inject `nest_asyncio`~~ → IPython autoawait handles it natively; dependency dropped
- [x] Session directory layout + JSONL trajectory
- [x] `opa_status` / `opa_kernel`

**Exit ✅** (all three enforced by `tests/test_kernel_integration.py`):

1. ✅ `files` (500 entries) set in one call, `len(files) == 500` in the next
2. ✅ 30 KB of output returns truncated; the full text lands in `outputs/00000.txt`
3. ✅ after a restart the variables are gone but `trajectory.jsonl` and the
   `rlm` symbols remain

Also settled here:

- Kernel transport is an **IPC socket**; TCP puts code and output in cleartext
  on localhost. Falls back to TCP if the socket path would exceed the limit.
- ANSI codes are stripped from tracebacks so they don't burn model context.
- Truncation always keeps the **tail** — a traceback's real cause is the last line.
- The kernel boots **lazily**; starting the MCP server is not a reason to start a kernel.

---

## Phase 2 — RLM: persistent sub-agents  (L2)  ✅ done

The reason this project exists.

- [x] `HostBridge` — Unix socket JSONL RPC, testable without a kernel
- [x] `opa_runtime` shim — the `rlm` symbols inside the kernel
- [x] `AgentAdapter` protocol + `claude-code` adapter
- [x] `ChildRegistry` — on disk; recovers after kernel/host restarts
- [x] `agent_message` — mailbox, parent → child resume
- [x] `codex` adapter

**Exit ✅** (`tests/test_rlm_integration.py`, against a real claude child):

1. ✅ `await rlm(...)` returns a handle in 0.6s; the child keeps running
2. ✅ after a kernel restart `list_subagents()` still lists it
3. ✅ `agent_message.send(...)` → the child **remembered the token from the turn
   before the restart** and answered with it
4. ✅ both adapters verified to resume with context (claude ALPHA-7, codex BETA-9)

Found and fixed along the way:

- **Protocol key shadowing**: a handler's `status:"running"` overwrote the
  protocol's `status:"ok"` and broke the client → results moved into a `result`
  envelope so it is structurally impossible.
- Both CLIs need **stdin closed** (codex blocks forever otherwise).
- codex needs `--skip-git-repo-check` outside a git repository.

---

## Phase 3 — Continual Harness  (L3)  ✅ done

- [x] `HarnessStore` CRUD, file-schema compatible with upstream
- [x] local / global scopes
- [x] **projection** — updates `CLAUDE.md` / `AGENTS.md` only inside delimiters
- [x] skill installation as `SKILL.md`, marked `.opa-managed`
- [x] `harness.evidence()` / `apply()` / `rollback()` with `before` snapshots
- [x] `opa_bootstrap` — the fourth and final tool
- [x] child → parent push — the one-tool `opa-child` server, `OPA_ROLE=child`

**Exit ✅**:

1. ✅ a new lesson becomes a `prompt` entry and lands in the file the host reads
2. ✅ projection leaves everything outside the delimiters byte-identical, and
   `remove` restores the original file exactly
3. ✅ rollback returns the harness to its exact prior state, including deletes

Also settled here:

- The harness does **not** decide what to change. Claude Code advertises no MCP
  `sampling` capability (measured), so the host does not lend us its model. We
  gather evidence, apply the delta, and keep it reversible.
- `auto` writes only to prompt files that already exist. Creating files the user
  never had is itself changing their environment.
- Ids keep Unicode word characters; stripping non-ASCII collapsed every Korean
  title onto one fallback id.
- A child gets the **one-tool** `opa-child` server, never the full one, so it
  cannot spawn grandchildren. That also answers the recursion-depth question the
  investigation list was holding open.
- The socket path must be passed to the adapter explicitly. It lives on the
  *kernel's* environment, not the server's, so copying `os.environ` left children
  unable to answer back — found by running it, not by reading it.

---

## Phase 4 — Long-run  (L4)  ✅ done

- [x] `goal` — create / get / complete, token budget accounting
- [x] ~~a separate `heartbeat` module~~ → an interval entry in `schedule`, with
      `source` keeping user-created and agent-created apart
- [x] `schedule` — one-time and cron
- [x] autonomous: max turns / token budget / wall clock + quality gate
- [x] feed a failed gate's output back in as the next input

**Exit ✅**: `autonomous.start(...)` drives a child until its gate exits 0,
feeding the gate's own failure output back in as the next prompt, and stops on
whichever of max turns / token budget / wall clock comes first.

Also settled here:

- The gate runs **off the event loop**. Inline it froze the bridge and every
  child callback for the gate's whole duration — a test suite is minutes.
- A turn that leaves the worktree byte-identical gets told so rather than handed
  the same gate failure again; an unchanged tree cannot produce a new result.
- Exhausting a budget is not completion. `budget_exhausted` is its own status
  and `completed_at` stays empty.
- No cron expressions. `at` / `in_seconds` / `every_seconds` cover a coding
  session, and a cron parser is a dependency and a bug class nobody asked for.

---

## Phase 5 — Evolution  ✅ core done

Depends on Phase 3. Feasibility already established experimentally
([concepts/evolution.md](concepts/evolution.md)).

- [x] `ToolSurface` — rebuild tool descriptions at runtime + `tools/list_changed`
- [x] `harness.evolve()` — apply a delta across all three layers, reversibly
- [ ] candidate children carrying a variant harness + a promotion gate
- [ ] human approval path via MCP `elicitation`

**What building it changed.** A tool description can remind an agent of what it
recorded while running; it cannot give standing to anything else. Claude Code
read our text verbatim and then declined to act on it, because it had no record
of creating the note — and no wording fixes that, since any provenance we assert
is more server-authored text. So the live surface carries an *index* of this
session's own notes, and authority comes from the project file. Written up with
the transcripts in [concepts/evolution.md](concepts/evolution.md#14-a-description-can-carry-a-rules-existence-not-its-authority).

---

## Phase 6 — Distribution

- [ ] `uvx open-primeagent` one-shot
- [ ] `install/claude-code.md` · `codex.md` · `opencode.md`
- [ ] Claude Code plugin (`/opa:refine`, `/opa:goal`, `/opa:status`)
- [ ] Example: a four-specialist resident team

---

## Non-goals

Explicitly **not** doing:

- A TUI or session UI — the host already has one
- A provider layer or OAuth — delegated to the host CLI
- Model fine-tuning — "self-improving" means the harness improves, not weights
- Feature parity with Prime Agent — we target the **portable RLM core**
