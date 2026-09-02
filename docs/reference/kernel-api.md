# Kernel API

Symbols preloaded inside the persistent kernel, reachable from
[`opa_python`](tools.md#opa_pythoncode-timeout1200). They are deliberately not
MCP tools.

Every call is `await`-ed; IPython's autoawait handles top-level `await`
natively.

---

## `rlm`

```python
await rlm(prompt, *, name, model=None, adapter=None, cwd=None, system_prompt=None)
```

Create an independent agent session and return **as soon as it is admitted** —
this does not wait for the child to finish.

> **Cost.** A child is a full coding-agent session and costs roughly 36k tokens
> before it reads any of your code
> ([measured](../../bench/README.md#0-sub-agent-fan-out--opa-loses-badly)).
> Spawn one only when the work would cost the parent more than that, and prefer
> `agent_message.send` to an existing child over a new one. See
> [when not to fan out](../concepts/rlm.md#when-not-to-fan-out).

| argument | meaning |
|---|---|
| `name` | **required.** The child's address for re-tasking later. Name it for its role (`backend`, `security`), because it is meant to stay. |
| `model` | passed straight to the host CLI, which is why there is no provider layer here |
| `adapter` | `"claude-code"` (default) or `"codex"` |
| `cwd` | must stay inside the workspace |
| `system_prompt` | a standing role spec, applied on every turn |
| `can_message_parent` | attach `opa_notify_parent` so the child can push progress mid-run |

Unknown keyword arguments raise `TypeError` rather than being ignored — a silent
`moodel="opus"` would run on the default model with nobody aware.

Returns an `RLMSpawnHandle` (`rlm_child_id`, `name`, `adapter`, `session_dir`,
`model`, `status`).

```python
await rlm.list_subagents()      # -> list[RLMSubagent], survives kernel restarts
await rlm.delete_subagent(name) # explicit only; nothing is reaped automatically
```

`RLMSubagent` carries `name`, `adapter`, `status`, `turns`, `tokens`,
`cost_usd`, `model`, `session_dir`, `last_error`.

## `agent_message`

```python
await agent_message.send(message, *, receiver_name, receiver_role="child")
```

Hand follow-up work to an existing child. It continues **with its earlier
context intact** — that is the whole point of the registry. Turns for one child
are serialized, so several sends queue rather than racing over the same session
file.

```python
await agent_message.inbox(since=0)   # -> list of records
```

Read the parent mailbox, where child results arrive. Each record has `at`,
`sender`, `receiver`, `message`, `rlm_child_id`, `ok`, `tokens`. A record with
`mid_run: true` is a progress note a child pushed while still working, not its
final answer.

Collection is a **pull**, not a push: we do not own the host's turn loop.

## `harness`

`H = (prompts, sub-agent specs, skills, memory)`. CRUD plus reversible
refinement.

```python
await harness.overview()                        # ids print as [local:id] / [global:id]
await harness.list(kind=None, scope="all")
await harness.get(entry_id)
await harness.create(kind, title, content, global_=False, **fields)
await harness.update(entry_id, **changes)
await harness.delete(entry_id)
```

`kind` is one of `prompt`, `memory`, `skill`, `subagent`. Ids printed by
`overview()` can be fed straight back, prefix included.

### Refinement

```python
evidence = await harness.evidence()
```

Grounds gathered from this session's trajectory. Each signal names the kind of
entry it argues for:

| signal | argues for |
|---|---|
| `repeated_errors` | a `prompt` policy or a `memory` fact |
| `repeated_commands` | a `skill` — a procedure being re-executed |
| `retasked_subagents` | a `subagent` spec — a delegation role that keeps recurring |
| `truncated_outputs` | work that should stay in the kernel rather than come back |

**Only repeated signals are candidates** — the
[benchmarks](../../bench/README.md) show that promoting something the model can
re-derive at a glance makes things measurably worse.

`past_refinements` comes back too, with what each was expected to achieve, so a
change that did not pay off becomes a rollback candidate rather than something
that quietly accumulates.

**What it cannot see.** These are signals of repetition, not of wrongness. The
most useful lesson of the session that produced this function came from a call
that *succeeded* and returned something stale; no trajectory shows that. Add
what you noticed yourself.

```python
event = await harness.apply(changes, trigger="...", evidence="...")
await harness.rollback(event["id"])
await harness.refinements()
```

`changes` is a list of operations:

```python
[{"op": "create", "kind": "prompt", "title": "...", "content": "..."},
 {"op": "update", "id": "ports", "content": "..."},
 {"op": "delete", "id": "stale-note"}]
```

If any operation fails, everything already applied is reverted and the call
raises. A half-applied harness is the worst possible outcome.

`rollback` restores the exact prior state from a `before` snapshot, including
entries that were deleted.

**The harness does not decide what to change.** Claude Code advertises no MCP
`sampling` capability ([measured](../concepts/evolution.md#11-what-the-host-declares)),
so the host does not lend us its model. You decide; we gather evidence, apply,
record, and make it reversible.

```python
await harness.project(agent="auto", remove=False)   # same as opa_bootstrap
```

## `goal`, `schedule`, `autonomous`

```python
await goal.create(objective, token_budget=None)   # one active goal at a time
await goal.get()
await goal.complete()                             # only when actually achieved
await goal.abandon(note="")                       # stopping without claiming success

await schedule.create(prompt, in_seconds=…)       # or at=… (ISO-8601), every_seconds=…
await schedule.list(source=None)                  # "user" | "agent"
await schedule.due(collect=True)                  # collect=False looks without consuming
await schedule.delete(entry_id)

await autonomous.start(objective, child_name=…, gate="pytest -q",
                       max_turns=5, token_budget=None, wall_clock_seconds=None)
await autonomous.status()
```

A goal cannot re-prompt you and a schedule cannot wake you — we do not own your
turn loop, so due items are collected on your next turn. `autonomous` is the
exception: it drives child processes itself, and **edits files and runs your
gate command unsupervised**. Full semantics and the safety notes are in
[long-running work](../concepts/long-run.md).
