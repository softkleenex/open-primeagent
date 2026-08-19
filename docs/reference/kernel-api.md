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

| argument | meaning |
|---|---|
| `name` | **required.** The child's address for re-tasking later. Name it for its role (`backend`, `security`), because it is meant to stay. |
| `model` | passed straight to the host CLI, which is why there is no provider layer here |
| `adapter` | `"claude-code"` (default) or `"codex"` |
| `cwd` | must stay inside the workspace |
| `system_prompt` | a standing role spec, applied on every turn |

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
`sender`, `receiver`, `message`, `rlm_child_id`, `ok`, `tokens`.

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

Grounds gathered from this session's trajectory: turn count, failed executions,
and `repeated_errors`. **Only repeated signals are promotion candidates** — the
[benchmarks](../../bench/README.md) show that promoting something the model can
re-derive at a glance makes things measurably worse.

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
