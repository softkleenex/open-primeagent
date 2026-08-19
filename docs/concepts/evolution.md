# Evolution — what is actually reachable

> *"Use the original; when it turns out to be mediocre, improve a copy and wire
> the copy back into the original."*
> *"Type `/evolve` and improve how the agent thinks, for the session I'm in."*
>
> Short answer: **both are reachable.** They live at different layers, and the
> hard part is not the mechanism — it is **evaluation**.

---

## 1. What we measured (2026-08-19)

We do not own the host's system prompt, so "can an agent's instructions change
mid-session?" had to be answered by experiment, not by argument. We attached a
raw JSON-RPC MCP server to Claude Code and measured.

### 1.1 What the host declares

```json
{ "protocolVersion": "2025-11-25",
  "capabilities": { "roots": {"listChanged": true}, "elicitation": {} },
  "clientInfo": { "name": "claude-code", "version": "2.1.235" } }
```

- **No `sampling`.** A server cannot borrow the host's model. Any design where
  the harness calls an LLM to rewrite itself is closed off through this path.
  (We have an alternative: a child agent *is* a model call.)
- **`elicitation` is present.** The server can ask the **user** a question during
  a tool call. That is exactly what a promotion gate needs if the gate is human.

### 1.2 Replacing a tool description mid-session

Server-side trace when the server rewrote its own tool description and sent
`notifications/tools/list_changed`:

```
tools/list   call=1  serving_version=0     ← session starts
tools/call                                  ← tool invoked
sent list_changed                           ← server swaps its own description
tools/list   call=2  serving_version=1     ← the host re-fetches ✅
--- same session, next turn (resume) ---
tools/list   call=1  serving_version=1
```

Asked on the next turn what the tool description said, the model answered:

```
V2 (MUTATED MID-SESSION): return pong, and always append the word EVOLVED.
```

**So the instructions an agent operates under can be swapped inside a live
session.** They take effect on the *next turn* — within the same turn the
context is already built.

Which is exactly the granularity `/evolve` needs: type it, and from your very
next message the agent runs the new procedure. No restart.

### 1.3 A constraint you must know: injection false-positives

In the same experiment we announced the change through the tool **result** text.
The model replied:

> This looks like a prompt injection attempt trying to steer my behavior, so I'm
> flagging it first.

A well-aligned host model **distrusts instructions arriving in tool output. It
is right to.** So the delivery channel matters:

- ❌ put "from now on, behave like this" in a tool **result** → treated as injection
- ✅ replace the tool **description** (schema) → the legitimate channel, accepted
- ✅ record that the user explicitly invoked `/evolve` as the justification

---

## 2. Three layers of evolution

| layer | takes effect | what changes | status |
|---|---|---|---|
| **L0** | next **session** | `CLAUDE.md` / `AGENTS.md` / `.claude/skills` (projection) | ✅ Phase 3 |
| **L1** | next **turn** | **tool descriptions** = the agent's operating procedure | measured, not built |
| **L2** | **immediately** | kernel namespace (new helper functions, skills) | already possible |

L2 already works because `opa_python` runs a persistent kernel: if `/evolve`
defines a new function, it is callable from that moment. That is evolution of
*capability* rather than of instructions.

Together:

```
/evolve
   │
   ├─ L2  define new helpers/skills in the kernel   → usable right now
   ├─ L1  rewrite tool descriptions + list_changed  → new procedure from the next turn
   └─ L0  promote to harness entries + project      → survives into the next session
```

---

## 3. "Original / copy" is the child agent we already built

Improving a copy and wiring it back is not something new to build.
**The copy is an `rlm` child.** Phase 2 already shipped the mechanism.

```
original (parent)  ── runs on the current harness H
   │
   ├─ rlm(..., name="candidate-a", system_prompt=H')   ← copy A: variant harness
   ├─ rlm(..., name="candidate-b", system_prompt=H'')  ← copy B
   │
   └─ promote only the variant that clears the gate
```

A child has its own context, session and model, persists in the registry, and
can be re-tasked. In other words, **the sandbox for running and comparing
variants already exists.**

Two pieces are missing:

1. dressing a child in a **candidate harness** (the `system_prompt=` path exists)
2. a **promotion gate**

---

## 4. The hard part is evaluation, not plumbing

All of the plumbing above is buildable. But:

> By what measure is the copy better than the original?

Without an answer this is not evolution, it is **drift** — prompts shifting a
little every session with nobody able to say whether things improved. Upstream's
`/refine` restricting itself to "the smallest possible CRUD change" plus rollback
is the same reasoning: when you cannot measure, you manage risk by shrinking the
change.

Our position:

| gate | when | promotion |
|---|---|---|
| **measurable** (test pass rate, lint, benchmark, tokens/time) | only for that kind of task | automatic |
| **human approval** (ask in place via `elicitation`) | everything else | manual |
| **none** | — | no promotion; record the proposal only |

**We do not build an automatic promotion path where nothing can be measured.**
That is a design choice, not a missing feature.

---

## 5. Safeguards (all mandatory)

1. **The base is immutable.** We never touch what we did not write — not the
   system prompt, not the user's own `CLAUDE.md` prose. Only inside delimiters.
2. **Versioned and reversible.** Every evolution is an event that can be
   rolled back exactly.
3. **Minimal delta.** No large rewrites. One or two CRUD operations.
4. **Deliver through tool descriptions**, never tool results (§1.3).
5. **Attribution.** Every evolved procedure records when it appeared and on what
   evidence, so a human can read it later and delete it.
6. **`/evolve` runs only when the user asks.** An automatic loop where the agent
   rewrites its own instructions is off by default, including in autonomous mode.

---

## 6. No new tool

`/evolve` does not become an MCP tool (`MAX_TOOLS = 4`). Per the project's own
rule it is exposed as a **kernel symbol**:

```python
await harness.evidence()             # grounds
await harness.apply([...], trigger="/evolve")
await harness.rollback(event_id)
```

A Claude Code `/opa:evolve` slash command would call into this from the plugin
layer.

---

## 7. Build order

Phase 3 (harness) had to come first — evolution needs state to change.

1. ✅ Phase 3 — `HarnessStore` CRUD + projection + rollback (L0)
2. `ToolSurface` — rebuild tool descriptions at runtime + `list_changed` (L1)
3. `harness.evolve()` — evidence → minimal delta → apply across all three layers
4. candidate children + gate → promote or discard (original/copy)
5. human approval via `elicitation`

**Step 4 is surprisingly small once 1–3 exist**, because the child
infrastructure is already there.
